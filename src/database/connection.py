import os
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "server_agent_db")
DB_USER = os.getenv("DB_USER", "app_user")
DB_PASS = os.getenv("DB_PASS", "")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def initialize_db():
    """스키마 생성 후 테이블 및 뷰 자동 생성"""
    try:
        # 모든 모델을 임포트해야 Base.metadata.create_all()이 인식함
        from src.modules.metrics.models import (
            CpuMetric, MemoryMetric, DiskMetric, NetworkMetric, DockerMetric
        )
        from src.modules.events.models import (
            LoginEvent, SystemEvent, CloudflareTunnel
        )
        from src.modules.runtime.models import TmuxSession
        
        with engine.connect() as conn:
            # 1. 기존 스키마 삭제 (리셋)
            if os.getenv("RESET_DB", "false").lower() == "true":
                print("⚠ WARNING: DB 스키마 리셋을 진행합니다...")
                conn.execute(text("DROP SCHEMA IF EXISTS ops_metrics CASCADE;"))
                conn.execute(text("DROP SCHEMA IF EXISTS ops_events CASCADE;"))
                conn.execute(text("DROP SCHEMA IF EXISTS ops_runtime CASCADE;"))
                conn.commit()
                print("✅ 기존 스키마 삭제 완료")
            
            # 2. PostgreSQL 스키마 다시 생성
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS ops_metrics;"))
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS ops_events;"))
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS ops_runtime;"))
            conn.commit()
            
            # 3. 테이블 생성
            Base.metadata.create_all(engine)
            
            # 4. 인간 친화적인 요약 뷰(View) 생성
            # (1) 자원 통합 요약
            view_resource_sql = """
            CREATE OR REPLACE VIEW ops_metrics.v_resource_summary AS
            SELECT
                c.ts AS "시각",
                c.batch_id AS "배치 ID",
                ROUND(c.cpu_percent::numeric, 2) || '%' AS "CPU 전체",
                ROUND(c.cpu_user::numeric, 2) || '%' AS "CPU 유저",
                ROUND(c.cpu_system::numeric, 2) || '%' AS "CPU 시스템",
                ROUND(m.mem_percent::numeric, 2) || '%' AS "RAM 사용률",
                ROUND(m.mem_used_mb::numeric, 0) || 'MB / ' || ROUND(m.mem_total_mb::numeric, 0) || 'MB' AS "RAM 상세",
                ROUND(d.disk_percent::numeric, 2) || '%' AS "디스크 사용률",
                ROUND(n.rx_rate_bps::numeric / 1024 / 1024, 2) || 'MB/s' AS "네트워크 수신",
                ROUND(n.tx_rate_bps::numeric / 1024 / 1024, 2) || 'MB/s' AS "네트워크 송신",
                '[Resource] CPU ' || ROUND(c.cpu_percent::numeric, 2) || '%, RAM ' ||
                ROUND(m.mem_percent::numeric, 2) || '%, Disk ' || ROUND(d.disk_percent::numeric, 2) || '%' AS "문장 요약"
            FROM ops_metrics.metrics_cpu c
            LEFT JOIN ops_metrics.metrics_memory m ON m.batch_id = c.batch_id
            LEFT JOIN (
                SELECT batch_id, MAX(disk_percent) AS disk_percent
                FROM ops_metrics.metrics_disk
                GROUP BY batch_id
            ) d ON d.batch_id = c.batch_id
            LEFT JOIN (
                SELECT batch_id, SUM(rx_rate_bps) AS rx_rate_bps, SUM(tx_rate_bps) AS tx_rate_bps
                FROM ops_metrics.metrics_network
                GROUP BY batch_id
            ) n ON n.batch_id = c.batch_id;
            """
            
            # (2) 도커 컨테이너 요약
            view_docker_sql = """
            CREATE OR REPLACE VIEW ops_metrics.v_docker_summary AS
            SELECT 
                id,
                ts AS "시각",
                container_name AS "컨테이너",
                ROUND(cpu_percent::numeric, 2) || '%' AS "CPU",
                ROUND(mem_percent::numeric, 2) || '%' AS "RAM 사용률",
                ROUND(mem_used_mb::numeric, 0) || 'MB' AS "RAM 사용량",
                '[Docker] ' || container_name || ': ' || ROUND(cpu_percent::numeric, 2) || '% CPU, ' || 
                ROUND(mem_percent::numeric, 2) || '% RAM (' || ROUND(mem_used_mb::numeric, 0) || 'MB)' AS "문장 요약"
            FROM ops_metrics.docker_metrics;
            """

            # (3) 런타임(Tmux) 상태 요약
            view_runtime_sql = """
            CREATE OR REPLACE VIEW ops_runtime.v_runtime_summary AS
            SELECT 
                id,
                ts AS "시각",
                session_name AS "세션명",
                windows AS "윈도우수",
                CASE WHEN attached THEN '연결됨' ELSE '대기중' END AS "상태",
                '[Runtime] Tmux: ' || session_name || ' (' || windows || ' windows, attached: ' || 
                (CASE WHEN attached THEN 'Yes' ELSE 'No' END) || ')' AS "문장 요약"
            FROM ops_runtime.tmux_sessions;
            """

            conn.execute(text(view_resource_sql))
            conn.execute(text(view_docker_sql))
            conn.execute(text(view_runtime_sql))
            conn.execute(text(
                "COMMENT ON VIEW ops_metrics.v_resource_summary IS "
                "'CPU/RAM/디스크/네트워크 요약을 한 줄로 제공하는 통합 뷰. LLM 기본 조회용.';"
            ))
            conn.execute(text(
                "COMMENT ON VIEW ops_metrics.v_docker_summary IS "
                "'도커 컨테이너별 CPU/RAM 요약을 제공하는 뷰.';"
            ))
            conn.execute(text(
                "COMMENT ON VIEW ops_runtime.v_runtime_summary IS "
                "'tmux 세션 상태를 요약해서 보여주는 뷰.';"
            ))
            conn.commit()
            
            print("✅ DB 초기화 및 모든 요약 뷰(Summary Views) 생성 완료")
    except Exception as e:
        print(f"❌ DB 초기화 실패: {e}")
