import sqlite3
import os
import threading
from typing import List, Dict, Optional, Tuple

class Database:
    """
    针对 6 万+ 文件断点续传设计的高性能本地 SQLite 状态存储
    """
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # 开启 WAL 模式加速并发写入
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self.lock, self._get_connection() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                file_name TEXT,
                file_size INTEGER,
                parsed_time TEXT,
                status TEXT DEFAULT 'PENDING',  -- PENDING, PROCESSING, SUCCESS, SKIPPED, FAILED
                detail TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON files(status);")
            conn.commit()

    def clear_all(self):
        with self.lock, self._get_connection() as conn:
            conn.execute("DELETE FROM files;")
            conn.commit()

    def get_success_filepaths(self) -> set:
        """获取所有已成功修复的文件完整路径集合，供增量扫描秒级比对跳过"""
        with self.lock, self._get_connection() as conn:
            cursor = conn.execute("SELECT file_path FROM files WHERE status = 'SUCCESS';")
            return {row["file_path"] for row in cursor.fetchall()}

    def batch_insert_scanned_files(self, file_records: List[Tuple[str, str, int, Optional[str], str, str]]):
        """
        批量插入或更新扫描到的文件记录：
        对于历史已经是 SUCCESS 的记录坚决保持不变，仅更新或新增非成功记录
        """
        with self.lock, self._get_connection() as conn:
            conn.executemany("""
            INSERT INTO files (file_path, file_name, file_size, parsed_time, status, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                parsed_time = excluded.parsed_time,
                status = excluded.status,
                detail = excluded.detail,
                updated_at = CURRENT_TIMESTAMP
            WHERE files.status != 'SUCCESS';
            """, file_records)
            conn.commit()

    def update_file_status(self, file_path: str, status: str, detail: str = ""):
        with self.lock, self._get_connection() as conn:
            conn.execute("""
            UPDATE files 
            SET status = ?, detail = ?, updated_at = CURRENT_TIMESTAMP
            WHERE file_path = ?;
            """, (status, detail, file_path))
            conn.commit()

    def batch_update_file_status(self, updates: List[Tuple[str, str, str]]):
        """
        批量更新文件状态与详情，大幅减少多线程下的事务提交开销
        updates: [(status, detail, file_path), ...]
        """
        if not updates:
            return
        with self.lock, self._get_connection() as conn:
            conn.executemany("""
            UPDATE files 
            SET status = ?, detail = ?, updated_at = CURRENT_TIMESTAMP
            WHERE file_path = ?;
            """, updates)
            conn.commit()

    def get_stats(self) -> Dict[str, int]:
        with self.lock, self._get_connection() as conn:
            cursor = conn.execute("""
            SELECT status, COUNT(*) as count FROM files GROUP BY status;
            """)
            stats = {"TOTAL": 0, "PENDING": 0, "SUCCESS": 0, "SKIPPED": 0, "FAILED": 0, "PROCESSING": 0}
            for row in cursor.fetchall():
                st = row["status"]
                cnt = row["count"]
                stats[st] = cnt
                stats["TOTAL"] += cnt
            return stats

    def get_pending_files(self, limit: int = 500) -> List[Dict]:
        with self.lock, self._get_connection() as conn:
            cursor = conn.execute("""
            SELECT id, file_path, file_name, file_size, parsed_time 
            FROM files 
            WHERE status = 'PENDING'
            LIMIT ?;
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def query_files(self, status: Optional[str] = None, search: Optional[str] = None, page: int = 1, page_size: int = 50) -> Dict:
        """
        带文件名搜索、状态筛选与完整分页支持的文件查询
        """
        where_clauses = []
        params = []

        if status and status != "ALL":
            where_clauses.append("status = ?")
            params.append(status)

        if search and search.strip():
            kw = f"%{search.strip()}%"
            where_clauses.append("(file_name LIKE ? OR file_path LIKE ?)")
            params.extend([kw, kw])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with self.lock, self._get_connection() as conn:
            # 统计符合条件的总记录数
            count_cursor = conn.execute(f"SELECT COUNT(*) as total FROM files {where_sql};", params)
            total = count_cursor.fetchone()["total"]

            page = max(1, page)
            page_size = max(1, min(page_size, 500))
            offset = (page - 1) * page_size

            query_sql = f"""
            SELECT id, file_path, file_name, file_size, parsed_time, status, detail, updated_at
            FROM files 
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?;
            """
            cursor = conn.execute(query_sql, params + [page_size, offset])
            rows = []
            for r in cursor.fetchall():
                d = dict(r)
                d["dir_name"] = os.path.dirname(d["file_path"])
                rows.append(d)

            total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "files": rows
            }

    def update_manual_time(self, file_id: int, new_time: str) -> bool:
        """手动设置单个文件的时间，并重置为待修复状态"""
        with self.lock, self._get_connection() as conn:
            cursor = conn.execute("""
            UPDATE files
            SET parsed_time = ?, status = 'PENDING', detail = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
            """, (new_time, f"[手动指定时间] {new_time}", file_id))
            conn.commit()
            return cursor.rowcount > 0

    def batch_update_manual_time(self, file_ids: List[int], start_time_str: str, step_seconds: int = 1) -> int:
        """批量手动指定时间，支持每张自动递增若干秒防止相册时间完全重叠"""
        from datetime import datetime, timedelta
        try:
            base_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            # 支持 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS
            start_time_str = start_time_str.replace("T", " ")
            if len(start_time_str) == 10:
                start_time_str += " 00:00:00"
            elif len(start_time_str) == 16:
                start_time_str += ":00"
            base_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")

        updates = []
        for i, fid in enumerate(file_ids):
            t_dt = base_dt + timedelta(seconds=i * step_seconds)
            t_str = t_dt.strftime("%Y-%m-%d %H:%M:%S")
            updates.append((t_str, f"[手动指定时间] {t_str}", fid))

        with self.lock, self._get_connection() as conn:
            conn.executemany("""
            UPDATE files
            SET parsed_time = ?, status = 'PENDING', detail = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
            """, updates)
            conn.commit()
            return len(updates)

    def get_recent_files(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        with self.lock, self._get_connection() as conn:
            cursor = conn.execute("""
            SELECT file_path, file_name, file_size, parsed_time, status, detail, updated_at
            FROM files 
            ORDER BY id DESC
            LIMIT ? OFFSET ?;
            """, (limit, offset))
            return [dict(row) for row in cursor.fetchall()]
