"""课程联合查询与响应字段映射的单元测试。"""

from course_query import (
    ACADEMIC_CONTEXT_FIELDS,
    COURSE_TYPE_CODES,
    COURSE_TYPE_LABELS,
    SPORTS_COURSE_TYPE_LABELS,
    CourseSearchCriteria,
    build_available_course_types_payload,
    build_course_query_payload,
    enrich_course_query_payload,
    extract_academic_context,
    extract_available_course_type_codes,
    extract_course_search_results,
    remove_empty_values,
    resolve_available_course_type_code,
)


def test_sports_course_tabs_use_dynamic_available_course_rules() -> None:
    """验证体育页签不再使用猜测的静态选课方式代码。"""
    assert SPORTS_COURSE_TYPE_LABELS == ("体育I", "体育II", "体育III")
    assert all(label in COURSE_TYPE_LABELS for label in SPORTS_COURSE_TYPE_LABELS)
    assert not any(label in COURSE_TYPE_CODES for label in SPORTS_COURSE_TYPE_LABELS)


def test_available_course_rules_resolve_real_sports_code() -> None:
    """验证从当前用户规则中读取并匹配体育课程实际代码。"""
    rule_payload = {
        "xkgzszList": [
            {"xkfsmc": "必修课", "xkfsdm": "[[REQUIRED_CODE]]"},
            {"xkfsmc": "体育课Ⅲ（本科）", "xkfsdm": "[[SPORTS_THREE_CODE]]"},
            {"xkfsmc": "体育II", "xkfsdm": "[[SPORTS_TWO_CODE]]"},
            {"xkfsmc": "", "xkfsdm": "[[IGNORED_CODE]]"},
        ]
    }

    course_type_codes = extract_available_course_type_codes(rule_payload)

    assert course_type_codes["体育课Ⅲ（本科）"] == "[[SPORTS_THREE_CODE]]"
    assert (
        resolve_available_course_type_code("体育III", course_type_codes)
        == "[[SPORTS_THREE_CODE]]"
    )
    assert (
        resolve_available_course_type_code("体育II", course_type_codes)
        == "[[SPORTS_TWO_CODE]]"
    )


def test_available_course_rules_payload_uses_selected_courses_tab() -> None:
    """验证规则接口按教务前端的“已选”上下文获取规则。"""
    payload = build_available_course_types_payload("2026-2027-1")

    assert payload["p_xkfsdm"] == "yixuan"
    assert payload["p_kclb"] == ""
    assert payload["p_xnxq"] == "2026-20271"


def test_extract_academic_context_preserves_all_server_context_fields() -> None:
    """验证嵌套响应中的完整服务端学期上下文不会被丢弃。"""
    server_context = {
        "p_xn": "2026-2027",
        "p_xq": "1",
        "p_xnxq": "2026-20271",
        "p_dqxn": "2026-2027",
        "p_dqxq": "1",
        "p_dqxnxq": "2026-20271",
        "cxsfmt": "1",
    }
    response_payload = {
        "data": {
            "xsxkPage": {
                "unused": "[[UNRELATED_VALUE]]",
                **server_context,
            }
        }
    }

    extracted_context = extract_academic_context(response_payload)

    assert extracted_context == {
        field_name: server_context[field_name]
        for field_name in ACADEMIC_CONTEXT_FIELDS
    }


def test_remove_empty_values_removes_empty_values_recursively() -> None:
    """
    验证递归剔除空值时保留零值和布尔假值。

    Args:
        None.

    Returns:
        None: 测试仅通过断言验证清理后的结构。
    """
    raw_payload = {
        "null_value": None,
        "empty_text": "",
        "blank_text": "  ",
        "empty_list": [],
        "nested": {"empty": None, "zero": 0, "false": False},
        "items": [None, "", {"value": "保留"}, 0],
    }

    cleaned_payload = remove_empty_values(raw_payload)

    assert cleaned_payload == {
        "nested": {"zero": 0, "false": False},
        "items": [{"value": "保留"}, 0],
    }


def test_build_course_query_payload_combines_code_and_name_criteria() -> None:
    """
    验证课程代码和名称可同时写入查询负载。

    Args:
        None.

    Returns:
        None: 测试仅通过断言验证请求参数。
    """
    criteria = CourseSearchCriteria(
        course_code="1029005",
        course_name="世界科技文明史",
    )

    payload = build_course_query_payload(
        semester="2026-2027-1",
        course_type_code="bx-b-b",
        criteria=criteria,
    )

    assert payload["p_kcdm_cxrw"] == "1029005"
    # The official query page clears this special-session field before a
    # normal course-code search; sending the code there makes sports queries
    # return an empty result set.
    assert "p_kcdm_cxrw_zckc" not in payload
    assert payload["p_gjz"] == "世界科技文明史"
    assert "p_kc_gjz" not in payload
    assert "p_kclb" not in payload
    assert payload["p_xnxq"] == "2026-20271"
    assert payload["pageSize"] == "100"
    assert all(value != "" for value in payload.values())


def test_enrich_course_query_payload_omits_special_course_maintenance_filter() -> None:
    """验证课程任务查询不会发送会清空体育结果的特殊筛选字段。"""
    payload = enrich_course_query_payload(
        build_course_query_payload(
            semester="2026-2027-1",
            course_type_code="bx-b-b-ty3",
            criteria=CourseSearchCriteria("11101013", ""),
        )
    )

    assert "p_kkxnxq" not in payload


def test_extract_course_search_results_maps_requested_columns() -> None:
    """
    验证课程响应映射为界面所需字段并清理空值。

    Args:
        None.

    Returns:
        None: 测试仅通过断言验证映射结果。
    """
    response_payload = {
        "message": None,
        "kxrwList": {
            "list": [
                {
                    "id": "course-task-id",
                    "rwmc": "",
                    "kcdm": "1029005",
                    "kcmc": "世界科技文明史",
                    "kcxzmc": "任选",
                    "kclb": "2305",
                    "kclbdm": "[[PREFERRED_CATEGORY]]",
                    "kclbmc": "素质拓展-人文素养(素质拓展)",
                    "skyymc": "中文",
                    "jfzlbmc": "百分制",
                    "xf": "2.0",
                    "zxs": "32.0",
                    "kcxx": (
                        "<div class='ivu-tag-cyan'><span class='ivu-tag-text'>"
                        "1-16周,星期三第11-12节 逸夫楼202</span></div>"
                    ),
                    "zrl": "70",
                    "yxzrs": "108",
                    "kkyxmc": "人文素质教育中心",
                    "xiaoqumc": "校本部",
                    "unused": None,
                }
            ]
        },
    }

    results = extract_course_search_results(response_payload)

    assert len(results) == 1
    result = results[0]
    assert result.display_name == "世界科技文明史"
    assert result.course_code == "1029005"
    assert result.course_name == "世界科技文明史"
    assert result.course_nature == "任选"
    assert result.category_code == "[[PREFERRED_CATEGORY]]"
    assert result.course_category == "素质拓展-人文素养(素质拓展)"
    assert result.teaching_language == "中文"
    assert result.scoring_method == "百分制"
    assert result.credit == "2.0"
    assert result.class_hours == "32.0"
    assert result.schedule == "1-16周,星期三第11-12节 逸夫楼202"
    assert result.capacity_selected == "70/108"
    assert result.offering_college == "人文素质教育中心"
    assert result.campus == "校本部"
