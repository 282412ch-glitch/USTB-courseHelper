"""通过可见浏览器复现教务系统体育课程查询的只读诊断。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from course_query import extract_academic_context


ROOT = Path(__file__).resolve().parent
STATUS_PATH = ROOT / "sports_live_probe_status.json"
STOP_PATH = ROOT / "sports_live_probe_stop.signal"
CHROME_PROFILE_PATH = ROOT / ".sports_live_probe_chrome"
CHROMEDRIVER_LOG_PATH = ROOT / "sports_live_probe_chromedriver.log"
BASE_URL = "https://byyt.ustb.edu.cn"


def write_status(payload: Mapping[str, Any]) -> None:
    """写入不含凭据的诊断状态。"""
    STATUS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def post_json(driver: webdriver.Chrome, path: str, payload: Mapping[str, str]) -> dict[str, Any]:
    """在已登录浏览器页面内发送同源表单请求。"""
    response = driver.execute_async_script(
        """
        const path = arguments[0];
        const payload = arguments[1];
        const done = arguments[arguments.length - 1];
        fetch(path, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest"
          },
          body: new URLSearchParams(payload).toString()
        }).then(async (result) => {
          done({status: result.status, body: await result.text()});
        }).catch((error) => done({status: 0, body: String(error)}));
        """,
        path,
        dict(payload),
    )
    if not isinstance(response, dict):
        return {"status": 0, "error": "浏览器未返回诊断结果"}
    body = response.get("body")
    result: dict[str, Any] = {"status": response.get("status")}
    if not isinstance(body, str):
        result["error"] = "接口响应不是文本"
        return result
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        result["error"] = body[:500]
        return result
    if isinstance(parsed, dict):
        result["payload"] = parsed
    else:
        result["error"] = "接口响应不是 JSON 对象"
    return result


def find_mapping_with_key(value: object, key: str) -> Mapping[str, Any] | None:
    """递归找到包含给定字段的首个对象。"""
    if isinstance(value, Mapping):
        if key in value:
            return value
        for child in value.values():
            found = find_mapping_with_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_mapping_with_key(child, key)
            if found is not None:
                return found
    return None


def find_list_with_key(value: object, key: str) -> list[object]:
    """递归找到指定列表字段，找不到时返回空列表。"""
    if isinstance(value, Mapping):
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
        for child in value.values():
            found = find_list_with_key(child, key)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_list_with_key(child, key)
            if found:
                return found
    return []


def text_value(value: object) -> str:
    """将可用接口字段规范为字符串。"""
    return str(value) if value is not None else ""


def build_context_payload(context: Mapping[str, Any]) -> dict[str, str]:
    """从官网返回的学期上下文构造规则查询的基础请求。"""
    values = {
        "cxsfmt": "1",
        "p_pylx": "1",
        "mxpylx": "1",
        "p_sfgldjr": "0",
        "p_sfredis": "0",
        "p_sfsyxkgwc": "0",
        "p_xktjz": "",
        "p_sfhlctkc": "0",
        "p_sfhllrlkc": "0",
        "p_sfxsgwckb": "1",
    }
    for key in (
        "cxsfmt",
        "p_pylx",
        "mxpylx",
        "p_sfgldjr",
        "p_sfredis",
        "p_sfsyxkgwc",
        "p_xktjz",
        "p_xn",
        "p_xq",
        "p_xnxq",
        "p_dqxn",
        "p_dqxq",
        "p_dqxnxq",
        "p_sfhlctkc",
        "p_sfhllrlkc",
        "p_sfxsgwckb",
    ):
        value = context.get(key)
        if value is not None:
            values[key] = text_value(value)
    # queryXkdqXnxq may only return the current-term (p_dq*) fields.  The
    # official page reuses those values as the selected term when building the
    # subsequent queryYxkc request, so fill the p_x* aliases here as well.
    values["p_xn"] = values.get("p_xn") or values.get("p_dqxn", "")
    values["p_xq"] = values.get("p_xq") or values.get("p_dqxq", "")
    values["p_xnxq"] = values.get("p_xnxq") or (
        f"{values['p_xn']}{values['p_xq']}"
        if values.get("p_xn") and values.get("p_xq")
        else ""
    )
    return values


def result_count(payload: Mapping[str, Any]) -> tuple[int | None, int]:
    """返回任务列表的总数和当前页条数。"""
    task_container = find_mapping_with_key(payload, "kxrwList")
    if task_container is not None:
        task_container = task_container.get("kxrwList")
    if not isinstance(task_container, Mapping):
        return None, 0
    total_value = task_container.get("total")
    total = int(total_value) if isinstance(total_value, (int, float, str)) and str(total_value).isdigit() else None
    items = task_container.get("list")
    return total, len(items) if isinstance(items, list) else 0


def response_summary(payload: object) -> dict[str, Any]:
    """提取查询响应中的非敏感结构字段，便于判断接口分支。"""
    if not isinstance(payload, Mapping):
        return {"kind": type(payload).__name__}
    summary: dict[str, Any] = {"keys": sorted(str(key) for key in payload.keys())}
    for key in ("jg", "message", "msg", "code", "status"):
        value = payload.get(key)
        if value is not None:
            summary[key] = str(value)[:300]
    for key in ("xkgzszOne", "kxrwList", "xsxkPage"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            summary[f"{key}_keys"] = sorted(str(child) for child in value.keys())
            if key == "kxrwList":
                items = value.get("list")
                summary["kxrwList_total"] = value.get("total")
                summary["kxrwList_count"] = len(items) if isinstance(items, list) else 0
        elif value is not None:
            summary[f"{key}_type"] = type(value).__name__
    return summary


def course_summary(payload: object) -> list[dict[str, Any]]:
    """提取体育任务的必要字段，不写出 Cookie 或其他凭据。"""
    if not isinstance(payload, Mapping):
        return []
    task_list = payload.get("kxrwList")
    if not isinstance(task_list, Mapping) or not isinstance(task_list.get("list"), list):
        return []
    allowed_fields = (
        "id", "rwmc", "kcdm", "kcmc", "dgjsmc", "kclbdm", "kclb", "kclbmc",
        "zrl", "yxzrs", "kcxx", "xkfsdm", "xnxq", "xn", "xq",
    )
    result: list[dict[str, Any]] = []
    for item in task_list["list"]:
        if not isinstance(item, Mapping):
            continue
        row = {
            field: item[field]
            for field in allowed_fields
            if field in item and item[field] not in (None, "")
        }
        result.append(row)
    return result


def run_probe(driver: webdriver.Chrome) -> dict[str, Any]:
    """读取官网上下文、规则及每个体育规则的首个查询页。"""
    context_response = post_json(driver, "/Xsxk/queryXkdqXnxq", {})
    context_payload = context_response.get("payload")
    if not isinstance(context_payload, Mapping):
        return {
            "state": "failed",
            "stage": "queryXkdqXnxq",
            "http_status": context_response.get("status"),
            "error": context_response.get("error", "未得到学期上下文"),
        }
    normalized_context = extract_academic_context(context_payload)
    context = normalized_context or (
        find_mapping_with_key(context_payload, "p_xn") or context_payload
    )
    safe_context = {
        key: text_value(context.get(key))
        for key in ("p_xn", "p_xq", "p_xnxq", "p_dqxn", "p_dqxq", "p_dqxnxq", "cxsfmt")
        if context.get(key) is not None
    }
    rule_payload = build_context_payload(context)
    rule_payload.update({"p_xkfsdm": "yixuan", "p_kclb": ""})
    rules_response = post_json(driver, "/Xsxk/queryYxkc", rule_payload)
    rules_payload = rules_response.get("payload")
    if not isinstance(rules_payload, Mapping):
        return {
            "state": "failed",
            "stage": "queryYxkc",
            "context": safe_context,
            "http_status": rules_response.get("status"),
            "error": rules_response.get("error", "未得到选课规则"),
        }
    raw_rules = find_list_with_key(rules_payload, "xkgzszList")
    rules = [rule for rule in raw_rules if isinstance(rule, Mapping)]
    safe_rules = [
        {"xkfsmc": text_value(rule.get("xkfsmc")), "xkfsdm": text_value(rule.get("xkfsdm"))}
        for rule in rules
        if rule.get("xkfsmc") is not None or rule.get("xkfsdm") is not None
    ]
    sports_rules = [
        rule
        for rule in safe_rules
        if "体育" in rule["xkfsmc"] or "体能" in rule["xkfsmc"]
    ]
    only_label = os.environ.get("SPORTS_PROBE_ONLY", "").strip()
    if only_label:
        sports_rules = [
            rule
            for rule in sports_rules
            if rule["xkfsmc"] == only_label
        ]
    sports_queries: list[dict[str, Any]] = []
    for rule in sports_rules:
        course_payload = dict(rule_payload)
        probe_code = os.environ.get("SPORTS_PROBE_CODE", "").strip()
        probe_name = os.environ.get("SPORTS_PROBE_NAME", "体育").strip()
        course_payload.update(
            {
                "p_xkfsdm": rule["xkfsdm"],
                "p_xktjz": "rwtjzyx",
                "p_kcdm_cxrw": probe_code,
                "p_kcdm_cxrw_zckc": "",
                "p_gjz": probe_name,
                "pageNum": "1",
                "pageSize": "100",
            }
        )
        course_response = post_json(driver, "/Xsxk/queryKxrw", course_payload)
        course_response_payload = course_response.get("payload")
        total, page_count = (
            result_count(course_response_payload)
            if isinstance(course_response_payload, Mapping)
            else (None, 0)
        )
        sports_queries.append(
            {
                "xkfsmc": rule["xkfsmc"],
                "xkfsdm": rule["xkfsdm"],
                "http_status": course_response.get("status"),
                "total": total,
                "page_count": page_count,
                "error": course_response.get("error"),
                "response": response_summary(course_response_payload),
                "courses": course_summary(course_response_payload),
            }
        )
        # The service rate-limits queryKxrw aggressively.  Keep the diagnostic
        # single-request by default, and leave a small gap for multi-rule runs.
        if len(sports_rules) > 1:
            time.sleep(5)
    return {
        "state": "completed",
        "context": safe_context,
        "rule_count": len(safe_rules),
        "rules": safe_rules,
        "sports_rules": sports_rules,
        "sports_queries": sports_queries,
    }


def is_logged_in(driver: webdriver.Chrome) -> bool:
    """以当前页面和同源上下文判断统一认证是否已完成。"""
    url = driver.current_url
    # The unified-authentication callback lands on /authentication/main after
    # a successful scan; the probe then navigates into Xsxk itself.
    if "/authentication/main" not in url and "/Xsxk/" not in url:
        return False
    return bool(driver.get_cookies())


def get_chrome_binary() -> Path:
    """定位已安装的 Chrome 可执行文件。"""
    candidates = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Google/Chrome/Application/chrome.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("未找到 Google Chrome，请确认浏览器已安装")


def find_free_local_port() -> int:
    """申请一个可用于 Chrome 调试的本机端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_debugger(port: int, timeout_seconds: float = 30.0) -> None:
    """等待浏览器调试端口就绪。"""
    deadline = time.monotonic() + timeout_seconds
    target = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(target, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Chrome 调试端口未在限定时间内就绪")


def terminate_browser(browser_process: subprocess.Popen[object] | None) -> None:
    """关闭本诊断脚本自行启动的 Chrome 进程树。"""
    if browser_process is None or browser_process.poll() is not None:
        return
    subprocess.run(
        ["taskkill.exe", "/PID", str(browser_process.pid), "/T", "/F"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    """启动浏览器，等待人工登录后执行只读诊断。"""
    STOP_PATH.unlink(missing_ok=True)
    browser_process: subprocess.Popen[object] | None = None
    driver: webdriver.Chrome | None = None
    try:
        debug_port = find_free_local_port()
        browser_process = subprocess.Popen(
            [
                str(get_chrome_binary()),
                f"--user-data-dir={CHROME_PROFILE_PATH}",
                f"--remote-debugging-port={debug_port}",
                "--start-maximized",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )
        wait_for_debugger(debug_port)
        options = Options()
        options.debugger_address = f"127.0.0.1:{debug_port}"
        service = Service(log_output=str(CHROMEDRIVER_LOG_PATH))
        service.service_args = ["--verbose"]
        driver = webdriver.Chrome(options=options, service=service)
    except WebDriverException as error:
        write_status({"state": "failed", "stage": "start_browser", "error": str(error)})
        return 1
    driver.set_script_timeout(35)
    try:
        driver.get(f"{BASE_URL}/Xsxk/query/1")
        write_status({"state": "awaiting_login"})
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline and not STOP_PATH.exists():
            if is_logged_in(driver):
                driver.get(f"{BASE_URL}/Xsxk/query/1")
                time.sleep(3)
                write_status(run_probe(driver))
                break
            time.sleep(1)
        else:
            if STOP_PATH.exists():
                write_status({"state": "stopped"})
            else:
                write_status({"state": "timeout", "error": "等待登录超时"})
        hold_deadline = time.monotonic() + 300
        while time.monotonic() < hold_deadline and not STOP_PATH.exists():
            time.sleep(1)
    except Exception as error:
        write_status({"state": "failed", "stage": "runtime", "error": str(error)})
        return 1
    finally:
        if driver is not None:
            driver.quit()
        terminate_browser(browser_process)
    return 0


if __name__ == "__main__":
    sys.exit(main())
