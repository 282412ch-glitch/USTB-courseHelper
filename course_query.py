"""选课任务联合查询的请求构造、空值清理与展示字段映射。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from bs4 import BeautifulSoup


COURSE_TYPE_CODES: dict[str, str] = {
    "素质扩展课": "sztzk-b-b",
    "专业扩展课": "zytzk-b-b",
    "MOOC": "mooc-b-b",
    "必修课": "bx-b-b",
}

# 体育选课方式代码会随学期和学生的选课规则变化，不能在客户端静态猜测。
SPORTS_COURSE_TYPE_LABELS: tuple[str, ...] = ("体育I", "体育II", "体育III")
COURSE_TYPE_LABELS: tuple[str, ...] = (
    *COURSE_TYPE_CODES,
    *SPORTS_COURSE_TYPE_LABELS,
)

# 教务系统在进入选课页时会先用该上下文表单初始化学期和筛选状态。
ACADEMIC_CONTEXT_FIELDS: tuple[str, ...] = (
    "p_xn",
    "p_xq",
    "p_xnxq",
    "p_dqxn",
    "p_dqxq",
    "p_dqxnxq",
    "cxsfmt",
)
ACADEMIC_CONTEXT_REQUIRED_FIELDS: tuple[str, ...] = (
    "p_xn",
    "p_xq",
    "p_xnxq",
)


DISPLAY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("display_name", "展示名称"),
    ("course_code", "课程代码"),
    ("course_name", "课程名称"),
    ("course_nature", "课程性质"),
    ("course_category", "课程类别"),
    ("teaching_language", "授课语言"),
    ("scoring_method", "计分方式"),
    ("credit", "学分"),
    ("class_hours", "学时"),
    ("schedule", "上课信息"),
    ("capacity_selected", "容量/已选"),
    ("offering_college", "开课学院"),
    ("campus", "校区"),
)


@dataclass(frozen=True)
class CourseSearchCriteria:
    """课程联合查询的可选筛选条件。"""

    course_code: str
    course_name: str

    def has_condition(self) -> bool:
        """
        判断是否至少提供了课程代码或课程名称筛选条件。

        Args:
            None.

        Returns:
            True 表示课程代码或课程名称中至少有一项非空。
        """
        return any((self.course_code, self.course_name))


@dataclass(frozen=True)
class CourseSearchResult:
    """课程检索结果在界面展示与加入课程列表所需的数据。"""

    task_id: str
    category_code: str
    display_name: str
    course_code: str
    course_name: str
    course_nature: str
    course_category: str
    teaching_language: str
    scoring_method: str
    credit: str
    class_hours: str
    schedule: str
    capacity_selected: str
    offering_college: str
    campus: str
    teacher: str

    def display_values(self) -> tuple[str, ...]:
        """
        按课程结果表的列顺序返回展示值。

        Args:
            None.

        Returns:
            与 DISPLAY_COLUMNS 顺序一致的字符串元组。
        """
        return tuple(getattr(self, field_name) for field_name, _ in DISPLAY_COLUMNS)


def remove_empty_values(value: object) -> object:
    """
    递归移除 JSON 数据中的空值、空文本、空列表和空对象。

    Args:
        value: 需要清理的 JSON 兼容对象。

    Returns:
        保留有效数据的新对象，数值 0 和布尔值 False 不会被移除。
    """
    if isinstance(value, Mapping):
        cleaned_mapping = {
            str(key): cleaned_value
            for key, item in value.items()
            if not _is_empty(cleaned_value := remove_empty_values(item))
        }
        return cleaned_mapping

    if isinstance(value, list):
        cleaned_list = [
            cleaned_value
            for item in value
            if not _is_empty(cleaned_value := remove_empty_values(item))
        ]
        return cleaned_list

    return value


def build_course_query_payload(
    semester: str,
    course_type_code: str,
    criteria: CourseSearchCriteria,
    page_number: int = 1,
    page_size: int = 100,
) -> dict[str, str]:
    """
    构造选课任务接口的联合查询负载。

    Args:
        semester: `YYYY-YYYY-N` 格式的学年学期。
        course_type_code: 选课方式代码，例如 `bx-b-b`。
        criteria: 课程代码和名称筛选条件。
        page_number: 请求页码，必须大于零。
        page_size: 单页数量，必须大于零。

    Returns:
        可直接作为 form-urlencoded 数据发送的非空参数字典。

    Raises:
        ValueError: 当学期格式错误、没有筛选条件或分页参数无效时抛出。
    """
    semester_parts = semester.split("-")
    if len(semester_parts) != 3 or not all(semester_parts):
        raise ValueError("学期格式错误，请使用 YYYY-YYYY-N 格式")
    if not criteria.has_condition():
        raise ValueError("请至少填写课程代码或课程名称之一")
    if page_number < 1 or page_size < 1:
        raise ValueError("页码和每页数量必须为正整数")

    academic_year = "-".join(semester_parts[:2])
    term = semester_parts[2]
    payload = {
        "cxsfmt": "1",
        "p_pylx": "1",
        "mxpylx": "1",
        "p_sfgldjr": "0",
        "p_sfredis": "0",
        "p_sfsyxkgwc": "0",
        "p_xktjz": "rwtjzyx",
        "p_xn": academic_year,
        "p_xq": term,
        "p_xnxq": f"{academic_year}{term}",
        "p_dqxn": academic_year,
        "p_dqxq": term,
        "p_dqxnxq": f"{academic_year}{term}",
        "p_xkfsdm": course_type_code,
        "p_sfhlctkc": "0",
        "p_sfhllrlkc": "0",
        "p_sfxsgwckb": "1",
        "pageNum": str(page_number),
        "pageSize": str(page_size),
    }
    optional_payload = {
        "p_kcdm_cxrw": criteria.course_code,
        "p_gjz": criteria.course_name,
    }
    payload.update(
        {key: value for key, value in optional_payload.items() if value.strip()}
    )
    return payload


def build_academic_context_payload() -> dict[str, str]:
    """构造官网初始化学年学期上下文所需的完整表单。

    Args:
        None.

    Returns:
        可直接提交到 ``Xsxk/queryXkdqXnxq`` 的表单字典。
    """
    return {
        "cxsfmt": "0",
        "p_pylx": "1",
        "mxpylx": "1",
        "p_sfgldjr": "0",
        "p_sfredis": "0",
        "p_sfsyxkgwc": "0",
        "p_xktjz": "",
        "p_chaxunxh": "",
        "p_gjz": "",
        "p_skjs": "",
        "p_xn": "",
        "p_xq": "",
        "p_xnxq": "",
        "p_dqxn": "",
        "p_dqxq": "",
        "p_dqxnxq": "",
        "p_xkfsdm": "",
        "p_xiaoqu": "",
        "p_kkyx": "",
        "p_kclb": "",
        "p_xkxs": "",
        "p_dyc": "",
        "p_kkxnxq": "99",
        "p_id": "",
        "p_ids": "",
        "p_sfhlctkc": "0",
        "p_sfhllrlkc": "0",
        "p_kxsj_xqj": "",
        "p_kxsj_ksjc": "",
        "p_kxsj_jsjc": "",
        "p_kcdm_js": "",
        "p_kcdm_cxrw": "",
        "p_kcdm_cxrw_zckc": "",
        "p_kc_gjz": "",
        "p_xzcxtjz_nj": "",
        "p_xzcxtjz_yx": "",
        "p_xzcxtjz_zy": "",
        "p_xzcxtjz_zyfx": "",
        "p_xzcxtjz_bj": "",
        "p_sfxsgwckb": "1",
        "p_skyy": "",
        "p_sfmxzj": "0",
        "p_chaxunxkfsdm": "",
    }


def enrich_course_query_payload(payload: Mapping[str, object]) -> dict[str, str]:
    """将官网完整的空筛选字段合并到课程任务查询负载。

    Args:
        payload: 已包含学期、选课方式和分页条件的查询负载。

    Returns:
        适合提交到 ``Xsxk/queryKxrw`` 的字符串字典；调用方字段优先。
    """
    enriched = build_academic_context_payload()
    enriched.update({str(key): str(value) for key, value in payload.items()})
    # ``p_kkxnxq=99`` is a special course-maintenance filter.  The official
    # query form leaves it unset for ``queryKxrw``; sending it causes the
    # sports task endpoint to return an empty list even when matching tasks
    # exist.  Keep it available for the context/rule requests, but omit it
    # from the task-query payload assembled here.
    enriched.pop("p_kkxnxq", None)
    return enriched


def build_available_course_types_payload(semester: str) -> dict[str, str]:
    """
    构造读取当前学生可用选课规则的请求负载。

    `Xsxk/queryYxkc` 返回的 ``xkgzszList`` 是选课方式代码的唯一可靠来源，
    体育 I/II/III 尤其不能使用固定代码。

    Args:
        semester: `YYYY-YYYY-N` 格式的学年学期。

    Returns:
        可作为 form-urlencoded 数据提交的规则查询参数。

    Raises:
        ValueError: 学期格式不正确时抛出。
    """
    semester_parts = semester.split("-")
    if len(semester_parts) != 3 or not all(semester_parts):
        raise ValueError("学期格式错误，请使用 YYYY-YYYY-N 格式")

    academic_year = "-".join(semester_parts[:2])
    term = semester_parts[2]
    payload = build_academic_context_payload()
    payload.update(
        {
            "cxsfmt": "1",
            "p_xn": academic_year,
            "p_xq": term,
            "p_xnxq": f"{academic_year}{term}",
            "p_dqxn": academic_year,
            "p_dqxq": term,
            "p_dqxnxq": f"{academic_year}{term}",
            # 教务前端切到“已选”页时请求该接口以取得 xkgzszList。
            "p_xkfsdm": "yixuan",
            "p_kclb": "",
        }
    )
    return payload


def extract_academic_context(
    response_payload: Mapping[str, object],
) -> dict[str, str]:
    """从学期上下文接口响应提取服务端学期字段。

    Args:
        response_payload: ``Xsxk/queryXkdqXnxq`` 返回的 JSON 对象。

    Returns:
        学期上下文字段映射；响应格式不完整时返回空字典。
    """
    cleaned_payload = remove_empty_values(response_payload)
    candidate = _find_academic_context_mapping(cleaned_payload)
    if candidate is None and isinstance(cleaned_payload, Mapping):
        # Some deployments return the current term fields at the response root
        # while nesting the selected-term fields elsewhere.
        candidate = cleaned_payload
    if candidate is None:
        return {}
    context = {
        field_name: _raw_value(candidate, field_name)
        for field_name in ACADEMIC_CONTEXT_FIELDS
        if _raw_value(candidate, field_name)
    }
    # Some deployments only return the current-term (``p_dq*``) values from
    # ``queryXkdqXnxq``.  The official page then uses those same values as the
    # selected term, so normalize them before validating the query context.
    context["p_xn"] = context.get("p_xn") or context.get("p_dqxn", "")
    context["p_xq"] = context.get("p_xq") or context.get("p_dqxq", "")
    context["p_xnxq"] = context.get("p_xnxq") or (
        f"{context['p_xn']}{context['p_xq']}"
        if context["p_xn"] and context["p_xq"]
        else ""
    )
    context["p_dqxn"] = context.get("p_dqxn") or context["p_xn"]
    context["p_dqxq"] = context.get("p_dqxq") or context["p_xq"]
    context["p_dqxnxq"] = context.get("p_dqxnxq") or (
        f"{context['p_dqxn']}{context['p_dqxq']}"
        if context["p_dqxn"] and context["p_dqxq"]
        else ""
    )
    context["cxsfmt"] = context.get("cxsfmt") or "1"
    if not all(
        context.get(field_name) for field_name in ACADEMIC_CONTEXT_REQUIRED_FIELDS
    ):
        return {}
    return {
        field_name: context[field_name]
        for field_name in ACADEMIC_CONTEXT_FIELDS
    }


def extract_available_course_type_codes(
    response_payload: Mapping[str, object],
) -> dict[str, str]:
    """
    从可用选课规则响应提取课程类型名称到实际选课方式代码的映射。

    Args:
        response_payload: `Xsxk/queryYxkc` 返回的 JSON 对象。

    Returns:
        课程类型名称到非空 ``xkfsdm`` 的映射；无有效规则时返回空字典。
    """
    cleaned_payload = remove_empty_values(response_payload)
    if not isinstance(cleaned_payload, Mapping):
        return {}
    rules = cleaned_payload.get("xkgzszList")
    if not isinstance(rules, list):
        page_data = cleaned_payload.get("xsxkPage")
        if isinstance(page_data, Mapping):
            rules = page_data.get("xkgzszList")
    if not isinstance(rules, list):
        return {}

    course_type_codes: dict[str, str] = {}
    for rule in rules:
        if not isinstance(rule, Mapping):
            continue
        course_type_name = _raw_value(rule, "xkfsmc")
        course_type_code = _raw_value(rule, "xkfsdm")
        if course_type_name and course_type_code:
            course_type_codes.setdefault(course_type_name, course_type_code)
    return course_type_codes


def resolve_available_course_type_code(
    course_type_label: str,
    available_course_type_codes: Mapping[str, str],
) -> str | None:
    """
    按界面课程类型名称查找当前会话的实际选课方式代码。

    教务系统偶尔会用罗马数字字符显示体育 I/II/III，因此比较时会统一
    处理空白和这些数字字符，但仍返回服务端原始 ``xkfsdm``。

    Args:
        course_type_label: 界面中选择的课程类型名称。
        available_course_type_codes: 从 `xkgzszList` 提取的类型映射。

    Returns:
        对应的实际选课方式代码；规则不存在时返回 None。
    """
    target_label = _normalize_course_type_label(course_type_label)
    for available_label, course_type_code in available_course_type_codes.items():
        if _normalize_course_type_label(available_label) == target_label:
            return course_type_code
    return None


def extract_course_search_results(
    response_payload: Mapping[str, object],
) -> list[CourseSearchResult]:
    """
    清理接口响应并提取课程检索结果的展示字段。

    Args:
        response_payload: 选课任务接口返回的 JSON 对象。

    Returns:
        按响应顺序排列的课程检索结果列表；无有效课程时返回空列表。
    """
    cleaned_payload = remove_empty_values(response_payload)
    if not isinstance(cleaned_payload, dict):
        return []
    task_list = cleaned_payload.get("kxrwList")
    if not isinstance(task_list, dict):
        return []
    courses = task_list.get("list")
    if not isinstance(courses, list):
        return []

    return [
        _map_course_result(course)
        for course in courses
        if isinstance(course, Mapping) and _value(course, "id")
    ]


def _is_empty(value: object) -> bool:
    """
    判断值是否应在清理 JSON 时移除。

    Args:
        value: 待判断的对象。

    Returns:
        True 表示值为 None、空白文本、空列表或空对象。
    """
    return value is None or (isinstance(value, str) and not value.strip()) or value in (
        [],
        {},
    )


def _value(course: Mapping[str, object], field_name: str) -> str:
    """
    读取课程字段并统一为空缺展示符号。

    Args:
        course: 单条课程任务的字段映射。
        field_name: 需要读取的接口字段名。

    Returns:
        去除首尾空白后的字段文本；字段不存在或为空时返回 `—`。
    """
    value = course.get(field_name)
    if value is None:
        return "—"
    text = str(value).strip()
    return text if text else "—"


def _raw_value(mapping: Mapping[str, object], field_name: str) -> str:
    """
    读取映射中的非空原始字符串值。

    Args:
        mapping: 接口对象字段映射。
        field_name: 需要读取的字段名。

    Returns:
        去除首尾空白后的文本；字段为空时返回空字符串。
    """
    value = mapping.get(field_name)
    if value is None:
        return ""
    return str(value).strip()


def _find_academic_context_mapping(value: object) -> Mapping[str, object] | None:
    """递归查找包含学期上下文字段的响应对象。

    Args:
        value: 已解析的接口响应对象。

    Returns:
        第一个包含完整必要学期字段的映射；找不到时返回 ``None``。
    """
    if isinstance(value, Mapping):
        if _has_academic_context_term(value):
            return value
        for child in value.values():
            found = _find_academic_context_mapping(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_academic_context_mapping(child)
            if found is not None:
                return found
    return None


def _has_academic_context_term(value: Mapping[str, object]) -> bool:
    """判断响应对象是否包含选中或当前学期的一组字段。

    Args:
        value: 候选接口响应对象。

    Returns:
        True 表示可由 ``p_x*`` 或 ``p_dq*`` 字段恢复学期。
    """
    return all(
        _raw_value(value, field_name)
        for field_name in ("p_xn", "p_xq")
    ) or all(
        _raw_value(value, field_name)
        for field_name in ("p_dqxn", "p_dqxq")
    )


def _normalize_course_type_label(value: str) -> str:
    """
    规范化课程类型名称以兼容体育课程的数字写法。

    Args:
        value: 课程类型名称。

    Returns:
        去除空白并统一罗马数字后的类型名称。
    """
    normalized = "".join(value.split()).translate(
        str.maketrans(
            {
                "Ⅰ": "I",
                "Ⅱ": "II",
                "Ⅲ": "III",
                "（": "(",
                "）": ")",
            }
        )
    )
    normalized = normalized.replace("(", "").replace(")", "")
    sports_match = re.match(
        r"^体育(?:课)?(I{1,3}|[1-3])",
        normalized,
        re.IGNORECASE,
    )
    if sports_match:
        numeral = sports_match.group(1).upper()
        numeral = {"1": "I", "2": "II", "3": "III"}.get(numeral, numeral)
        return f"体育{numeral}"
    return normalized


def _map_course_result(course: Mapping[str, object]) -> CourseSearchResult:
    """
    将一条选课任务映射为课程查询结果。

    Args:
        course: 已剔除空值的选课任务字段映射。

    Returns:
        可供界面展示和加入课程列表的课程结果对象。
    """
    display_name = _value(course, "rwmc")
    course_name = _value(course, "kcmc")
    if display_name == "—":
        display_name = course_name

    capacity = f"{_value(course, 'zrl')}/{_value(course, 'yxzrs')}"
    scoring_method = _value(course, "jfzlbmc")
    if scoring_method == "—":
        scoring_method = _value(course, "jfxs")

    return CourseSearchResult(
        task_id=_value(course, "id"),
        category_code=_value(
            course,
            "kclbdm" if _raw_value(course, "kclbdm") else "kclb",
        ),
        display_name=display_name,
        course_code=_value(course, "kcdm"),
        course_name=course_name,
        course_nature=_value(course, "kcxzmc"),
        course_category=_value(course, "kclbmc"),
        teaching_language=_value(course, "skyymc"),
        scoring_method=scoring_method,
        credit=_value(course, "xf"),
        class_hours=_value(course, "zxs"),
        schedule=_extract_schedule(_value(course, "kcxx")),
        capacity_selected=capacity,
        offering_college=_value(course, "kkyxmc"),
        campus=_value(course, "xiaoqumc"),
        teacher=_value(course, "dgjsmc"),
    )


def _extract_schedule(course_html: str) -> str:
    """
    从课程信息 HTML 中提取所有青色标签的上课时间与地点。

    Args:
        course_html: 接口 `kcxx` 字段中的 HTML 片段。

    Returns:
        使用换行拼接的上课信息；不存在时返回 `—`。
    """
    if course_html == "—":
        return "—"
    document = BeautifulSoup(course_html, "html.parser")
    schedule_tags = document.select(".ivu-tag-cyan .ivu-tag-text")
    schedules = [tag.get_text(" ", strip=True) for tag in schedule_tags]
    return "\n".join(schedule for schedule in schedules if schedule) or "—"
