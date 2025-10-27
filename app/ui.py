from __future__ import annotations

# =============================================================
# UI 유틸리티: 자산 설정 로드, 사이드바 렌더링, 실행 게이트 등
# - 자산 설정 파일(assets.json) 처리
# - 체크박스/버튼 등 사이드바 입력 요소 구성
# - 실행 파라미터 세션 상태 관리
# =============================================================

from pathlib import Path
import json
from typing import Tuple, Dict, List

import streamlit as st


def load_assets_config(project_root: Path) -> List[Tuple[str, str, bool]]:
    """자산 설정 파일(assets.json)을 읽어 (심볼, 표시명, 기본활성) 튜플 목록으로 반환합니다.

    파일이 없거나 형식 오류인 경우 안전한 기본 자산 목록을 반환합니다.
    """
    assets_path = project_root / "assets.json"
    if assets_path.exists():
        try:
            with open(assets_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                parsed = [
                    (
                        a.get("symbol", ""),
                        a.get("name", a.get("symbol", "")),
                        bool(a.get("enabled", True)),
                    )
                    for a in cfg.get("assets", [])
                    if a.get("symbol")
                ]
                if parsed:
                    return parsed
        except Exception:
            pass

    return [
        ("068270.KS", "Celltrion", True),
        ("GC=F", "Gold", True),
        ("^IXIC", "Nasdaq", True),
        ("^GSPC", "S&P 500", True),
        ("BTC-USD", "Bitcoin", True),
        ("^TNX", "10Y Treasury Yield", True),
        ("^VIX", "VIX", True),
    ]


def render_sidebar_assets(
    default_assets: List[Tuple[str, str, bool]],
) -> Tuple[List[str], Dict[str, str]]:
    """사이드바에 자산 체크박스를 렌더링하고 선택된 심볼과 표시명 매핑을 반환합니다."""
    st.sidebar.subheader("Select assets")
    selected_symbols: List[str] = []
    symbol_to_display: Dict[str, str] = {}
    for symbol, friendly, enabled in default_assets:
        include = st.sidebar.checkbox(friendly, value=enabled, key=f"asset_{symbol}")
        if include:
            selected_symbols.append(symbol)
            symbol_to_display[symbol] = friendly
    return selected_symbols, symbol_to_display


def gate_run_and_params(selected_symbols, period, start, end):
    """'Run' 버튼으로 실행을 제어하고, 선택 파라미터를 세션 상태에 저장합니다.

    반환값은 (실행여부, 파라미터 dict) 입니다.
    """
    run_clicked = st.sidebar.button("Run")
    if run_clicked:
        st.session_state["do_run"] = True
        st.session_state["run_params"] = {
            "symbols": tuple(selected_symbols),
            "period": period or "10d",
            "start": start,
            "end": end,
        }
    if not st.session_state.get("do_run"):
        return False, {}
    params = st.session_state.get(
        "run_params",
        {
            "symbols": tuple(selected_symbols),
            "period": period or "10d",
            "start": start,
            "end": end,
        },
    )
    return True, params


def apply_display_names(dfs_processed, selected_symbols, symbol_to_display) -> None:
    """전처리된 각 데이터프레임에 선택된 표시명을 'Name' 컬럼으로 주입합니다."""
    symbol_iter = iter(selected_symbols)
    for df in dfs_processed:
        try:
            symbol = next(symbol_iter)
        except StopIteration:
            break
        df["Name"] = symbol_to_display.get(symbol, symbol)
