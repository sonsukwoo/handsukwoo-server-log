import subprocess
import logging
from datetime import datetime
from src.database.connection import SessionLocal
from .models import TmuxSession

logger = logging.getLogger("RUNTIME")

def get_tmux_sessions():
    """
    tmux list-sessions 명령을 통해 세션 정보를 가져옴.
    호스트(UID 1000)의 세션을 보기 위해 소켓 경로를 명시적으로 지정함.
    """
    sessions = []
    
    # 호스트의 Tmux 소켓 경로 후보 (UID 1000 기준)
    # 보통 /tmp/tmux-1000/default 형식이지만, 파일명이 다를 수 있으므로 검색
    socket_path = None
    possible_dir = "/tmp/tmux-1000"
    
    import os
    if os.path.isdir(possible_dir):
        try:
            # 디렉토리 내의 첫 번째 파일을 소켓으로 가정 (보통 'default')
            files = os.listdir(possible_dir)
            if files:
                socket_path = os.path.join(possible_dir, files[0])
                logger.info(f"호스트 Tmux 소켓 발견: {socket_path}")
        except PermissionError:
             logger.warning(f"소켓 디렉토리({possible_dir}) 접근 권한이 없습니다. (컨테이너가 root인지 확인 필요)")

    # 명령 명령어 구성 (-S 옵션 사용)
    cmd = ['tmux']
    if socket_path:
        cmd.extend(['-S', socket_path])
    cmd.extend(['list-sessions', '-F', '#{session_name}:#{session_attached}:#{session_windows}'])

    try:
        # 포맷: 이름:접속여부(1 or 0):윈도우개수
        result = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            encoding='utf-8'
        )
        for line in result.strip().split('\n'):
            if ':' in line:
                parts = line.split(':')
                if len(parts) >= 3:
                    name, attached, windows = parts[0], parts[1], parts[2]
                    sessions.append({
                        "name": name,
                        "attached": True if attached == '1' else False,
                        "windows": int(windows) if windows.isdigit() else 0
                    })
    except FileNotFoundError:
        logger.warning("Tmux 명령어를 찾을 수 없습니다. (설치되어 있나요?)")
    except subprocess.CalledProcessError as e:
        # 정상적인 '세션 없음' 상태 또는 버전 불일치 확인
        output = e.output.strip() if e.output else ""
        if "no server running" in output or "failed to connect to server" in output:
            logger.info(f"실행 중인 Tmux 세션이 없습니다. (소켓: {socket_path})")
        elif "protocol version mismatch" in output:
             logger.error(f"Tmux 버전 불일치! (Host vs Container). 호스트의 tmux 버전을 업데이트하거나 컨테이너를 맞춰야 합니다. (Err: {output})")
        else:
            logger.warning(f"Tmux 조회 실패: {output}")
    except Exception as e:
        logger.error(f"Tmux 정보 추출 중 알 수 없는 오류: {e}")
        
    return sessions

def collect_runtime_status(ts=None):
    """
    Tmux 세션 등의 런타임 상태 정보를 수집하여 DB에 저장 (Tier 2: 1분 주기)
    """
    if ts is None:
        ts = datetime.now()

    db = SessionLocal()
    try:
        # 1. Tmux 세션 정보 수집
        sessions = get_tmux_sessions()
        
        objs_to_save = []
        for s in sessions:
            new_session = TmuxSession(
                ts=ts,
                session_name=s['name'],
                attached=s['attached'],
                windows=s['windows']
            )
            objs_to_save.append(new_session)
        
        if objs_to_save:
            db.bulk_save_objects(objs_to_save)
            db.commit()
            logger.info(f"런타임 상태 저장 완료 (Tmux: {len(objs_to_save)}개 세션)")
            return f"Runtime: {len(objs_to_save)} tmux sessions collected"
        
    except Exception as e:
        db.rollback()
        logger.error(f"런타임 수집 중 오류 발생: {e}")
        return None
    finally:
        db.close()
