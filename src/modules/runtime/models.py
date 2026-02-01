from sqlalchemy import Column, Integer, Text, DateTime, Boolean
from sqlalchemy.sql import func
from src.database.connection import Base

# ------------------------------------------------------------
# 3. 런타임 상태 (ops_runtime 스키마)
# ------------------------------------------------------------

class TmuxSession(Base):
    """
    tmux 세션 상태 스냅샷
    """
    __tablename__ = "tmux_sessions"
    __table_args__ = {
        "schema": "ops_runtime",
        "comment": "서버 내 tmux 세션 상태를 저장하는 테이블.",
    }

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    batch_id = Column(Text, index=True, comment="수집 사이클을 구분하는 배치 ID")

    session_name = Column(Text, nullable=False, index=True, comment="tmux 세션 이름.")
    attached = Column(Boolean, comment="현재 세션에 접속 중인지 여부.")
    windows = Column(Integer, comment="세션 내 윈도우 개수.")
    created_at = Column(DateTime(timezone=True), comment="tmux 세션 생성 시각.")
