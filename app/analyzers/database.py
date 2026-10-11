import os
import re
from typing import List, Optional
from app.models.schemas import DatabaseInfo, ScanResult

class DatabaseAnalyzer:
    DB_SIGNATURES = {
        'PostgreSQL': ['psycopg2', 'postgresql', 'sqlalchemy', 'pg'],
        'MySQL': ['mysql-connector', 'pymysql', 'mysqlclient'],
        'SQLite': ['sqlite3'],
        'MongoDB': ['pymongo', 'mongodb', 'mongoose'],
        'Redis': ['redis-py', 'redis'],
    }

    ORM_SIGNATURES = {
        'SQLAlchemy': ['sqlalchemy'],
        'Django ORM': ['django.db.models'],
        'Mongoose': ['mongoose'],
        'Hibernate': ['org.hibernate'],
        'Prisma': ['@prisma/client'],
    }

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def analyze(self, scan_result: ScanResult, project_analysis: any) -> Optional[DatabaseInfo]:
        # 1. Check Dependencies (from ProjectAnalysis)
        deps = project_analysis.repo_info.dependencies
        detected_db = None
        detected_orm = None

        for db, sigs in self.DB_SIGNATURES.items():
            if any(sig.lower() in [d.lower() for d in deps] for sig in sigs):
                detected_db = db
                break

        for orm, sigs in self.ORM_SIGNATURES.items():
            if any(sig.lower() in [d.lower() for d in deps] for sig in sigs):
                detected_orm = orm
                break

        # 2. Check Config Files for Connection Strings
        if not detected_db:
            for file in scan_result.files:
                if any(ext in file.path for ext in ['.env', '.properties', '.yaml', '.yml']):
                    content = self._read_file(file.path)
                    if 'postgres://' in content or 'postgresql://' in content:
                        detected_db = 'PostgreSQL'
                        break
                    if 'mongodb://' in content:
                        detected_db = 'MongoDB'
                        break
                    if 'mysql://' in content:
                        detected_db = 'MySQL'
                        break

        # 3. Check docker-compose.yml
        if not detected_db:
            docker_path = os.path.join(self.repo_path, "docker-compose.yml")
            if os.path.exists(docker_path):
                content = self._read_file("docker-compose.yml")
                if 'postgres' in content.lower(): detected_db = 'PostgreSQL'
                elif 'mongo' in content.lower(): detected_db = 'MongoDB'
                elif 'mysql' in content.lower(): detected_db = 'MySQL'
                elif 'redis' in content.lower(): detected_db = 'Redis'

        # 4. Detect Models
        models = []
        for file in scan_result.files:
            if file.extension in ['.py', '.js', '.ts', '.java']:
                content = self._read_file(file.path)
                # Simple patterns for model detection
                if 'class' in content and any(x in content.lower() for x in ['model', 'entity', 'schema']):
                    models.append(file.path)

        if not detected_db and not detected_orm and not models:
            return None

        return DatabaseInfo(
            db_type=detected_db or "Unknown",
            orm=detected_orm,
            models=models[:10] # Limit to top 10
        )

    def _read_file(self, rel_path: str) -> str:
        try:
            with open(os.path.join(self.repo_path, rel_path), 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception:
            return ""
