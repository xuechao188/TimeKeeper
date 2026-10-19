import os
import sys
import json
import time
import shutil
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from parser import TimeParser
from db import Database
from exif_writer import ExifWriter

DATA_DIR = os.environ.get("APP_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.environ.get("APP_STATIC_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "../ui"))
PORT = int(os.environ.get("APP_PORT", 28090))
DB_PATH = os.path.join(DATA_DIR, "timekeeper.db")

db = Database(DB_PATH)
parser = TimeParser()
writer = ExifWriter()

TASK_STATE = {
    "status": "IDLE",  # IDLE, SCANNING, RUNNING, PAUSED, FINISHED
    "current_path": "",
    "current_file": "",
    "scanned_count": 0,
    "speed": 0.0,
    "total": 0,
    "processed": 0,
    "success": 0,
    "skipped": 0,
    "failed": 0,
    "logs": []
}
task_lock = threading.Lock()
stop_flag = threading.Event()
pause_flag = threading.Event()

def add_log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{ts}] {msg}"
    with task_lock:
        TASK_STATE["logs"].append(log_entry)
        if len(TASK_STATE["logs"]) > 200:
            TASK_STATE["logs"].pop(0)

def scan_worker(target_dir: str, use_filename: bool = True, use_exif: bool = True, use_dir: bool = True, incremental: bool = True, use_ocr: bool = False):
    mode_text = "智能增量(跳过已修复)" if incremental else "全量覆盖重扫"
    add_log(f"开始扫描目录 [{mode_text}]: {target_dir} (文件名:{use_filename}, 内部Exif:{use_exif}, 目录继承:{use_dir}, 水印OCR:{use_ocr})")
    with task_lock:
        TASK_STATE["status"] = "SCANNING"
        TASK_STATE["current_path"] = target_dir
        TASK_STATE["scanned_count"] = 0
        TASK_STATE["current_file"] = "正在遍历并索引媒体文件..."

    if not incremental:
        db.clear_all()
        success_set = set()
    else:
        success_set = db.get_success_filepaths()
        if success_set:
            add_log(f"已载入 {len(success_set)} 个历史成功修复记录，本次扫描将自动极速跳过！")

    batch = []
    scanned_count = 0
    skipped_success_count = 0
    new_found_count = 0
    valid_exts = {
        ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".raw", ".cr2", ".nef", ".arw",
        ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".wmv"
    }

    start_scan_time = time.time()

    for root, _, files in os.walk(target_dir):
        if stop_flag.is_set():
            add_log("扫描任务被用户终止。")
            break
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in valid_exts:
                continue

            full_path = os.path.join(root, f)

            # 增量跳过：已成功修复的文件 O(1) 毫秒级直接跳过，零重复开销
            if incremental and full_path in success_set:
                skipped_success_count += 1
                continue

            scanned_count += 1
            new_found_count += 1
            if scanned_count % 50 == 0 or scanned_count <= 20:
                with task_lock:
                    TASK_STATE["scanned_count"] = scanned_count
                    TASK_STATE["current_file"] = f

            dt, method_desc = parser.fast_resolve_at_scan(
                full_path, 
                use_filename=use_filename, 
                use_exif=use_exif, 
                use_dir=use_dir,
                use_ocr=use_ocr
            )

            if dt:
                parsed_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                status = "PENDING"
                detail = f"[{method_desc}] 匹配时间: {parsed_time}"
            elif method_desc == "待执行阶段深度挖掘Exif":
                parsed_time = None
                status = "PENDING"
                detail = "[待挖掘Exif] 文件名未含时间，将在执行阶段直接提取内部拍摄时间"
            else:
                parsed_time = None
                status = "SKIPPED"
                detail = "所有已选模式均未匹配到有效时间"

            batch.append((full_path, f, 0, parsed_time, status, detail))

            if len(batch) >= 1000:
                db.batch_insert_scanned_files(batch)
                batch = []
                add_log(f"已极速检索并索引 {scanned_count} 个待处理/新增媒体文件...")

    if batch:
        db.batch_insert_scanned_files(batch)

    elapsed = max(0.1, round(time.time() - start_scan_time, 2))
    stats = db.get_stats()
    with task_lock:
        TASK_STATE["status"] = "IDLE"
        TASK_STATE["total"] = stats["TOTAL"]
        TASK_STATE["scanned_count"] = stats["TOTAL"]
        TASK_STATE["success"] = stats["SUCCESS"]
        TASK_STATE["skipped"] = stats["SKIPPED"]
        TASK_STATE["failed"] = stats["FAILED"]
        TASK_STATE["processed"] = stats["SUCCESS"] + stats["SKIPPED"] + stats["FAILED"]
        TASK_STATE["current_file"] = ""
    add_log(f"扫描完毕！耗时仅 {elapsed} 秒。新增/重分析: {new_found_count} 个，智能跳过历史已修复: {skipped_success_count} 个。当前队列待处理: {stats['PENDING']} 个")

def process_single_item(item, fix_exif: bool, fix_fs: bool, dry_run: bool):
    f_path = item["file_path"]
    f_name = item["file_name"]
    p_time = item["parsed_time"]
    detail_tag = ""

    if not p_time:
        extracted_dt = writer.extract_media_time(f_path)
        if extracted_dt:
            p_time = extracted_dt.strftime("%Y-%m-%d %H:%M:%S")
            detail_tag = "[原生Exif挖掘] "
        else:
            return f_path, f_name, "SKIPPED", "未能从文件内部Exif/元数据读取到拍摄时间"

    if dry_run:
        return f_path, f_name, "SUCCESS", f"[模拟] {detail_tag}拟同步时间: {p_time}"

    try:
        dt = datetime.strptime(p_time, "%Y-%m-%d %H:%M:%S")
        ok, msg = writer.fix_file_time(f_path, dt, fix_exif=fix_exif, fix_filesystem=fix_fs)
        if ok:
            return f_path, f_name, "SUCCESS", f"{detail_tag}已修复: {p_time}"
        else:
            return f_path, f_name, "FAILED", msg
    except Exception as e:
        return f_path, f_name, "FAILED", str(e)

def process_worker(fix_exif: bool, fix_fs: bool, dry_run: bool, concurrency: int = 4):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    concurrency = max(1, min(concurrency, 16))
    add_log(f"批处理任务启动: 并发线程数={concurrency}, fix_exif={fix_exif}, fix_fs={fix_fs}, dry_run={dry_run}")
    with task_lock:
        TASK_STATE["status"] = "RUNNING"

    start_time = time.time()
    processed_in_session = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        while not stop_flag.is_set():
            if pause_flag.is_set():
                with task_lock:
                    TASK_STATE["status"] = "PAUSED"
                time.sleep(1)
                continue
            else:
                with task_lock:
                    TASK_STATE["status"] = "RUNNING"

            fetch_limit = max(100, concurrency * 25)
            pending_items = db.get_pending_files(limit=fetch_limit)
            if not pending_items:
                stats = db.get_stats()
                if stats.get("SKIPPED", 0) > 0 and processed_in_session == 0:
                    add_log(f"当前队列已无待处理文件（检测到有 {stats['SKIPPED']} 个历史跳过文件）。若您刚升级了新规则，请先点击【全量扫描文件】即可极速重扫并重新激活这些跳过文件！")
                else:
                    add_log("所有待处理项已全部完成！")
                break

            futures = {
                executor.submit(process_single_item, item, fix_exif, fix_fs, dry_run): item
                for item in pending_items
            }

            status_updates = []
            for future in as_completed(futures):
                if stop_flag.is_set():
                    break
                while pause_flag.is_set() and not stop_flag.is_set():
                    with task_lock:
                        TASK_STATE["status"] = "PAUSED"
                    time.sleep(0.5)

                try:
                    f_path, f_name, status, detail = future.result()
                    status_updates.append((status, detail, f_path))
                    processed_in_session += 1

                    if processed_in_session % 5 == 0:
                        with task_lock:
                            TASK_STATE["current_file"] = f_name
                except Exception:
                    pass

                # 每 50 条批量持久化一次数据库，大幅减少 SQLite 锁争用
                if len(status_updates) >= 50:
                    db.batch_update_file_status(status_updates)
                    status_updates = []

                elapsed = time.time() - start_time
                if elapsed > 0:
                    with task_lock:
                        TASK_STATE["speed"] = round(processed_in_session / elapsed, 1)

            if status_updates:
                db.batch_update_file_status(status_updates)
                status_updates = []

            stats = db.get_stats()
            with task_lock:
                TASK_STATE["total"] = stats["TOTAL"]
                TASK_STATE["success"] = stats["SUCCESS"]
                TASK_STATE["skipped"] = stats["SKIPPED"]
                TASK_STATE["failed"] = stats["FAILED"]
                TASK_STATE["processed"] = stats["SUCCESS"] + stats["SKIPPED"] + stats["FAILED"]

    with task_lock:
        TASK_STATE["status"] = "FINISHED" if not stop_flag.is_set() else "IDLE"
        TASK_STATE["current_file"] = ""
        TASK_STATE["speed"] = 0.0
    add_log(f"批处理执行阶段结束。共处理 {processed_in_session} 个文件。")


class RequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        resp = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(resp)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(resp)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/api/status":
            stats = db.get_stats()
            with task_lock:
                data = dict(TASK_STATE)
                data["stats"] = stats
                data["has_exiftool"] = writer.has_exiftool
                data["ocr_status"] = parser.ocr_reader.get_status()
            self._send_json(data)
            return

        if path == "/api/files":
            qs = parse_qs(url.query)
            page = int(qs.get("page", [1])[0])
            page_size = int(qs.get("page_size", qs.get("limit", [50]))[0])
            status = qs.get("status", ["ALL"])[0].strip()
            search = qs.get("search", [""])[0].strip()
            result = db.query_files(status=status, search=search, page=page, page_size=page_size)
            self._send_json(result)
            return

        if path == "/api/roots":
            roots = []
            
            # 1. 扫描飞牛所有真实存储空间挂载点
            for v in ["/vol1", "/vol2", "/vol3", "/vol4", "/vol5"]:
                if os.path.exists(v) and os.path.isdir(v):
                    vol_name = v.replace("/vol", "存储空间 ")
                    roots.append({"name": f"📁 {vol_name} ({v})", "path": v})

            # 2. 读取飞牛授权环境变量（如有）
            auth_paths_env = os.environ.get("TRIM_DATA_ACCESSIBLE_PATHS", "")
            if auth_paths_env:
                for p in auth_paths_env.split(":"):
                    p = p.strip()
                    if p and os.path.exists(p):
                        if not any(r["path"] == p for r in roots):
                            roots.insert(0, {"name": f"⭐ 已授权文件夹: {os.path.basename(p)} ({p})", "path": p})

            # 3. 其它挂载点
            for c in ["/media", "/mnt"]:
                if os.path.exists(c) and os.path.isdir(c):
                    if not any(r["path"] == c for r in roots):
                        roots.append({"name": f"📁 外部存储 ({c})", "path": c})

            if not roots:
                roots = [{"name": "根目录 (/)", "path": "/"}]
            self._send_json({"roots": roots})
            return

        if path == "/api/browse":
            qs = parse_qs(url.query)
            req_path = qs.get("path", ["/"])[0].strip()
            if not req_path:
                req_path = "/"
            
            # 安全检查并列出子文件夹
            dirs = []
            try:
                if os.path.exists(req_path) and os.path.isdir(req_path):
                    for entry in os.scandir(req_path):
                        if entry.is_dir(follow_symlinks=False):
                            # 过滤隐藏文件夹以保持清爽
                            if not entry.name.startswith('.'):
                                dirs.append({"name": entry.name, "path": entry.path})
                    dirs.sort(key=lambda x: x["name"].lower())
            except Exception as e:
                self._send_json({"error": f"无法访问目录: {str(e)}"}, code=500)
                return

            parent = os.path.dirname(os.path.normpath(req_path)) if req_path != "/" else None
            self._send_json({
                "current": req_path,
                "parent": parent,
                "directories": dirs
            })
            return

        if path == "/api/preview":
            qs = parse_qs(url.query)
            target_path = qs.get("path", [""])[0].strip()
            # 兼容可能的多层 url 编码
            if target_path.startswith("%2F") or target_path.startswith("%2f"):
                target_path = unquote(target_path)

            if not target_path or not os.path.exists(target_path):
                self.send_error(404, f"File Not Found: {target_path}")
                return
            if not os.path.isfile(target_path):
                self.send_error(400, "Target is not a regular file")
                return

            ext = os.path.splitext(target_path)[1].lower()
            mime_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
                ".svg": "image/svg+xml"
            }
            if ext not in mime_types:
                self.send_error(400, "Unsupported media preview")
                return

            try:
                # 缩略图模式快速生成（悬停 320x320 预览，若支持 PIL）
                is_thumb = qs.get("thumb", ["0"])[0] in ("1", "true")
                if is_thumb:
                    try:
                        from PIL import Image, ImageOps
                        import io
                        with Image.open(target_path) as im:
                            try:
                                im = ImageOps.exif_transpose(im)
                            except Exception:
                                pass
                            if im.mode != "RGB":
                                im = im.convert("RGB")
                            im.thumbnail((320, 320))
                            buf = io.BytesIO()
                            im.save(buf, format="JPEG", quality=82)
                            thumb_bytes = buf.getvalue()
                            self.send_response(200)
                            self.send_header('Content-Type', 'image/jpeg')
                            self.send_header('Content-Length', str(len(thumb_bytes)))
                            self.send_header('Cache-Control', 'public, max-age=86400')
                            self.end_headers()
                            self.wfile.write(thumb_bytes)
                            return
                    except Exception:
                        pass # 回退到发送原图

                # 发送原图流（支持大图弹窗与新标签页打开）
                file_size = os.path.getsize(target_path)
                self.send_response(200)
                self.send_header('Content-Type', mime_types.get(ext, 'image/jpeg'))
                self.send_header('Content-Length', str(file_size))
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                with open(target_path, 'rb') as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                self.send_error(500, str(e))
            return

        # 静态文件服务
        static_file = path.lstrip('/')
        if not static_file or static_file == "":
            static_file = "index.html"
        full_static_path = os.path.join(STATIC_DIR, static_file)

        if os.path.exists(full_static_path) and os.path.isfile(full_static_path):
            content_type = "text/plain"
            if static_file.endswith(".html"):
                content_type = "text/html; charset=utf-8"
            elif static_file.endswith(".js"):
                content_type = "application/javascript"
            elif static_file.endswith(".css"):
                content_type = "text/css"
            elif static_file.endswith(".png"):
                content_type = "image/png"
            elif static_file.endswith(".ico"):
                content_type = "image/x-icon"

            with open(full_static_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "File Not Found")

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/api/scan":
            target_dir = payload.get("path", "").strip()
            use_filename = payload.get("use_filename", True)
            use_exif = payload.get("use_exif", True)
            use_dir = payload.get("use_dir", True)
            incremental = payload.get("incremental", True)
            use_ocr = payload.get("use_ocr", False)

            if not target_dir or not os.path.exists(target_dir):
                self._send_json({"error": "目录路径无效或不存在"}, code=400)
                return

            stop_flag.clear()
            pause_flag.clear()
            threading.Thread(target=scan_worker, args=(target_dir, use_filename, use_exif, use_dir, incremental, use_ocr), daemon=True).start()
            self._send_json({"message": "扫描任务已在后台启动"})
            return

        if path == "/api/clear_history":
            db.clear_all()
            with task_lock:
                TASK_STATE["total"] = 0
                TASK_STATE["processed"] = 0
                TASK_STATE["success"] = 0
                TASK_STATE["skipped"] = 0
                TASK_STATE["failed"] = 0
                TASK_STATE["scanned_count"] = 0
            add_log("已手动清空全部历史扫描与处理记录。")
            self._send_json({"message": "历史记录已清空"})
            return

        if path == "/api/start":
            fix_exif = payload.get("fix_exif", True)
            fix_fs = payload.get("fix_fs", True)
            dry_run = payload.get("dry_run", False)
            concurrency = int(payload.get("concurrency", 4))

            stop_flag.clear()
            pause_flag.clear()
            threading.Thread(target=process_worker, args=(fix_exif, fix_fs, dry_run, concurrency), daemon=True).start()
            self._send_json({"message": "处理任务已启动"})
            return

        if path == "/api/pause":
            pause_flag.set()
            add_log("任务已暂停")
            self._send_json({"message": "任务已暂停"})
            return

        if path == "/api/resume":
            pause_flag.clear()
            add_log("任务已恢复继续执行")
            self._send_json({"message": "任务已恢复"})
            return

        if path == "/api/stop":
            stop_flag.set()
            pause_flag.clear()
            add_log("任务收到终止指令")
            self._send_json({"message": "任务已停止"})
            return

        if path == "/api/update_time":
            file_id = payload.get("file_id")
            file_ids = payload.get("file_ids", [])
            new_time = payload.get("time", "").strip()
            step_seconds = int(payload.get("step_seconds", 1))

            if file_id is not None and file_id not in file_ids:
                file_ids = [file_id]

            if not file_ids:
                self._send_json({"error": "未提供要修改的文件 ID"}, code=400)
                return

            if not new_time:
                self._send_json({"error": "未提供有效的时间字符串"}, code=400)
                return

            try:
                cnt = db.batch_update_manual_time(file_ids, new_time, step_seconds=step_seconds)
                # 重新刷新全局任务统计
                stats = db.get_stats()
                with task_lock:
                    TASK_STATE["total"] = stats["TOTAL"]
                    TASK_STATE["success"] = stats["SUCCESS"]
                    TASK_STATE["skipped"] = stats["SKIPPED"]
                    TASK_STATE["failed"] = stats["FAILED"]
                    TASK_STATE["processed"] = stats["SUCCESS"] + stats["SKIPPED"] + stats["FAILED"]
                add_log(f"已手动为 {cnt} 个文件指定目标时间 (起始: {new_time}, 递增步长: {step_seconds}秒)，已转入待修复队列！")
                self._send_json({"success": True, "count": cnt, "message": f"成功修改 {cnt} 个文件的时间"})
            except Exception as e:
                self._send_json({"error": str(e)}, code=500)
            return

        if path == "/api/test_regex":
            test_str = payload.get("filename", "")
            dt = parser.parse(test_str)
            if dt:
                self._send_json({"success": True, "parsed": dt.strftime("%Y-%m-%d %H:%M:%S")})
            else:
                self._send_json({"success": False, "message": "未能识别出符合规则的日期时间"})
            return

        self.send_error(404, "Unknown API")

def run_server():
    server_address = ('0.0.0.0', PORT)
    httpd = HTTPServer(server_address, RequestHandler)
    print(f"TimeKeeper Server listening on http://0.0.0.0:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()

if __name__ == '__main__':
    run_server()
