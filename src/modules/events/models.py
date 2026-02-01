from sqlalchemy import Column, Integer, Text, DateTime
from src.database.connection import Base
from sqlalchemy.sql import func

# ------------------------------------------------------------
# 2. 이벤트 계열 (ops_events 스키마)
# ------------------------------------------------------------

class LoginEvent(Base):
    """
    서버 로그인/접속 기록
    """
    __tablename__ = "login_events"
    __table_args__ = {
        "schema": "ops_events",
        "comment": "서버 로그인/접속 기록 테이블.",
    }

    id = Column(Integer, primary_key=True, comment="행 식별자(PK).")
    ts = Column(DateTime(timezone=True), nullable=False, index=True, comment="수집 시각. 시간 범위 필터/정렬에 사용.")

    user_name = Column(Text, nullable=False, index=True, comment="접속 계정명.")
    tty = Column(Text, comment="터미널 (tty, pts 등).")
    remote_host = Column(Text, comment="접속 IP/호스트.")
    session_id = Column(Text, comment="세션 식별자.")


class SystemEvent(Base):
    """
    중요한 시스템 이벤트
    """
    __tablename__ = "system_events"
    __table_args__ = {
        "schema": "ops_events",
        "comment": "중요 시스템 이벤트 로그 테이블.",
    }

    id = Column(Integer, primary_key=True, comment="행 식별자(PK).")
    ts = Column(DateTime(timezone=True), nullable=False, index=True, comment="수집 시각. 시간 범위 필터/정렬에 사용.")

    event_type = Column(Text, comment="이벤트 타입 (ERROR/WARN/INFO 등).")
    severity = Column(Text, comment="심각도.")
    source = Column(Text, comment="발생 소스.")
    message = Column(Text, comment="이벤트 메시지.")


class CloudflareTunnel(Base):
    """
    Cloudflare Tunnel 상태 스냅샷
    """
    __tablename__ = "cloudflare_tunnels"
    __table_args__ = {
        "schema": "ops_events",
        "comment": "Cloudflare Tunnel 상태 기록 테이블.",
    }

    id = Column(Integer, primary_key=True, comment="행 식별자(PK).")
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True, comment="수집 시각. 시간 범위 필터/정렬에 사용.")

    tunnel_name = Column(Text, nullable=False, index=True, comment="터널 이름.")
    status = Column(Text, comment="상태.")
    error_message = Column(Text, comment="에러 메시지.")
