import os
import re
from datetime import datetime
from typing import Optional, Tuple

try:
    from app.backend.ocr_reader import WatermarkOCRReader
except ImportError:
    from ocr_reader import WatermarkOCRReader

class TimeParser:
    """
    轻量级纯内存极速解析引擎：
    在扫描阶段纯靠 CPU 内存级正则与层级字符串匹配，
    彻底消除外部子进程与重型 IO 开销，6 万文件扫描秒级完成！
    """
    def __init__(self):
        self.ocr_reader = WatermarkOCRReader()
        # 1. 文件名时间正则 (按匹配精度从高到低排列)
        self.filename_patterns = [
            # 1. 14位或含毫秒带分隔符的 ymd_hms (如 IMG_20230815_143025.jpg, 2023-08-15 14.30.25.jpg, PXL_20230815_143025123.jpg)
            (re.compile(r'(?:^|[^\d])(?:IMG|VID|Screenshot|P|PXL|PANO|REC|WP|mmexport)?[_-]?(20\d{2}|19\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])[\s_-]+([01]\d|2[0-3])[-_.:]?([0-5]\d)[-_.:]?([0-5]\d)(?:\d{3})?(?:\D|$)', re.IGNORECASE), "ymd_hms"),
            
            # 2. 14位纯连续数字 ymd_hms (如 20210515123045.jpg, IMG20210515123045.jpg)
            (re.compile(r'(?:^|[^\d])(?:IMG|VID|Screenshot|P|PXL|PANO|REC|WP)?[_-]?(20\d{2}|19\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?:\D|$)', re.IGNORECASE), "ymd_hms"),
            
            # 3. 12位纯连续数字 ymd_hm (如 202105151230.jpg)
            (re.compile(r'(?:^|[^\d])(20\d{2}|19\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([01]\d|2[0-3])([0-5]\d)(?:\D|$)', re.IGNORECASE), "ymd_hm"),
            
            # 4. 13位 Unix 时间戳毫秒 (如 mmexport1692085825000.jpg, 1692085825000.jpg)
            (re.compile(r'(?:^|[^\d])(?:mmexport)?(1[3-7]\d{11})(?:\D|$)', re.IGNORECASE), "timestamp_ms"),
            
            # 5. 10位 Unix 时间戳秒 (如 photo_1692085825.jpg)
            (re.compile(r'(?:^|[^\d])(1[3-7]\d{8})(?:\D|$)', re.IGNORECASE), "timestamp_s"),
            
            # 6. 中文年月日格式 (如 2008年03月21日.jpg, 2008年3月21日.jpg)
            (re.compile(r'(?:^|[^\d])(20\d{2}|19\d{2})年(\d{1,2})月(\d{1,2})日?(?:\D|$)', re.IGNORECASE), "ymd_only"),
            
            # 7. 8位日期 + 序号/编号/常规后缀 (如 20080321334.jpg, 20080321_01.jpg, 20080321(1).jpg, 2008-03-21.jpg)
            (re.compile(r'(?:^|[^\d])(?:IMG|VID|P|DSC)?[_-]?(20\d{2}|19\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?:[_-]?\d{1,5})?(?:\D|$)', re.IGNORECASE), "ymd_only")
        ]

        # 2. 目录层级时间正则（年月日、年月）
        self.dir_patterns = [
            (re.compile(r'(?:^|\D)(20\d{2}|19\d{2})[-_.年](\d{1,2})[-_.月](\d{1,2})[日]?(?:\D|$)', re.IGNORECASE), "ymd"),
            (re.compile(r'(?:^|\D)(20\d{2}|19\d{2})[-_.年](\d{1,2})[月]?(?:\D|$)', re.IGNORECASE), "ym")
        ]

    def parse_from_filename(self, filename: str) -> Optional[datetime]:
        base_name = os.path.basename(filename)
        name_without_ext, _ = os.path.splitext(base_name)

        for regex, rule_type in self.filename_patterns:
            match = regex.search(name_without_ext)
            if not match:
                continue

            try:
                if rule_type == "ymd_hms":
                    year, month, day, hour, minute, second = map(int, match.groups())
                    dt = datetime(year, month, day, hour, minute, second)
                elif rule_type == "ymd_hm":
                    year, month, day, hour, minute = map(int, match.groups())
                    dt = datetime(year, month, day, hour, minute, 0)
                elif rule_type == "timestamp_ms":
                    ts_ms = int(match.group(1))
                    dt = datetime.fromtimestamp(ts_ms / 1000.0)
                elif rule_type == "timestamp_s":
                    ts_s = int(match.group(1))
                    dt = datetime.fromtimestamp(float(ts_s))
                elif rule_type == "ymd_only":
                    year, month, day = map(int, match.groups())
                    dt = datetime(year, month, day, 0, 0, 0)
                else:
                    continue

                now = datetime.now()
                if 1970 <= dt.year <= (now.year + 1):
                    return dt
            except Exception:
                continue
        return None

    def parse_from_directory(self, full_path: str) -> Optional[datetime]:
        """
        目录层级时间深度提取：
        1. 支持单级目录年月日 (2015-12-05, 2015年12月5日, 20151205 等)
        2. 支持单级目录年月 (2015年12月, 2015-12, 2015.12, 201512 等)，自动补齐为当月1日
        3. 支持跨层级级联提取 (父目录为年份如 2015 或 2015年，子目录为月份如 12 或 12月)
        4. 支持纯年份目录 (2015年)，自动补齐为当年1月1日
        """
        curr = os.path.dirname(os.path.abspath(full_path))
        ignore_names = {
            "/", "\\", "vol1", "vol2", "vol3", "vol4", "volume1", "volume2", "volume3",
            "photos", "media", "photo", "video", "nas", "public", "homes", "home"
        }
        parts = []
        for _ in range(4):
            base = os.path.basename(curr)
            if not base or base.lower() in ignore_names:
                break
            parts.append(base)
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent

        if not parts:
            return None

        now = datetime.now()
        max_year = now.year + 1

        ymd_patterns = [
            re.compile(r'(?:^|[^\d])(19\d{2}|20\d{2})[-_.年](0?[1-9]|1[0-2])[-_.月](0?[1-9]|[12]\d|3[01])[日]?(?:\D|$)', re.IGNORECASE),
            re.compile(r'(?:^|[^\d])(19\d{2}|20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:\D|$)', re.IGNORECASE)
        ]
        ym_patterns = [
            re.compile(r'(?:^|[^\d])(19\d{2}|20\d{2})[-_.年](0?[1-9]|1[0-2])[月]?(?:\D|$)', re.IGNORECASE),
            re.compile(r'(?:^|[^\d])(19\d{2}|20\d{2})[-_.](0?[1-9]|1[0-2])(?:\D|$)', re.IGNORECASE),
            re.compile(r'(?:^|[^\d])(19\d{2}|20\d{2})(0[1-9]|1[0-2])(?:\D|$)', re.IGNORECASE)
        ]
        y_patterns = [
            re.compile(r'(?:^|[^\d])(19\d{2}|20\d{2})年(?:\D|$)', re.IGNORECASE),
            re.compile(r'^(19\d{2}|20\d{2})$', re.IGNORECASE)
        ]

        # 1. 优先扫描单级目录完整年月日
        for p in parts:
            for reg in ymd_patterns:
                m = reg.search(p)
                if m:
                    try:
                        y, mo, d = map(int, m.groups()[-3:])
                        if 1970 <= y <= max_year:
                            return datetime(y, mo, d, 0, 0, 0)
                    except Exception:
                        pass

        # 2. 扫描单级目录年月 (自动设为当月 1 日 0 点)
        for p in parts:
            for reg in ym_patterns:
                m = reg.search(p)
                if m:
                    try:
                        y, mo = map(int, m.groups()[-2:])
                        if 1970 <= y <= max_year:
                            return datetime(y, mo, 1, 0, 0, 0)
                    except Exception:
                        pass

        # 3. 跨层级级联分析：例如子目录为月份 (12 或 12月)，父目录为年份 (2015 或 2015年)
        for i in range(len(parts) - 1):
            child = parts[i]
            parent = parts[i + 1]
            m_month = re.search(r'^(0?[1-9]|1[0-2])[月]?$', child)
            m_year = re.search(r'^(19\d{2}|20\d{2})[年]?$', parent)
            if m_month and m_year:
                try:
                    y = int(m_year.group(1))
                    mo = int(m_month.group(1))
                    if 1970 <= y <= max_year:
                        return datetime(y, mo, 1, 0, 0, 0)
                except Exception:
                    pass

        # 4. 纯年份目录兜底 (如 2015年 或 2015，设为当年 1 月 1 日)
        for p in parts:
            for reg in y_patterns:
                m = reg.search(p)
                if m:
                    try:
                        y = int(m.group(1))
                        if 1970 <= y <= max_year:
                            return datetime(y, 1, 1, 0, 0, 0)
                    except Exception:
                        pass

        return None

    def fast_resolve_at_scan(self, full_path: str, use_filename: bool = True, use_exif: bool = True, use_dir: bool = True, use_ocr: bool = False) -> Tuple[Optional[datetime], str]:
        """
        极速扫描模式：
        1. 优先内存级纯正则（文件名）
        2. 其次内存级纯目录匹配
        3. 若均未匹配且勾选了'图片水印识别'，执行角部局部 OCR 兜底
        4. 若都没匹配到，且勾选了'内部原生Exif挖掘'，则标记为待执行阶段深度挖掘 Exif
        """
        if use_filename:
            dt = self.parse_from_filename(full_path)
            if dt:
                return dt, "文件名提取"

        if use_dir:
            dt = self.parse_from_directory(full_path)
            if dt:
                return dt, "目录年月继承"

        if use_ocr:
            ext = os.path.splitext(full_path)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png'):
                dt = self.ocr_reader.extract_time(full_path)
                if dt:
                    return dt, "照片水印识别"

        if use_exif:
            # 标记为待执行阶段深度探测 Exif
            return None, "待执行阶段深度挖掘Exif"

        return None, "未匹配到时间"

    def parse(self, filename: str) -> Optional[datetime]:
        """供前端规则沙盒即时测试调用的纯文件名正则解析接口"""
        return self.parse_from_filename(filename)
