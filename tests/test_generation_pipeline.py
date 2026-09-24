from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTENT_SERVICE_ROOT = REPOSITORY_ROOT / "services" / "content-service"


def _load_content_modules(service_importer):
    nodes = service_importer(CONTENT_SERVICE_ROOT, "app.graph.nodes")
    graph_state = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    request = importlib.import_module("app.models.request")
    return nodes, graph_state, presentation, request


def _analysis(graph_state, facts: list[str] | None = None):
    facts = facts or []
    return graph_state.ScriptAnalysis(
        topic="Результаты",
        audience="",
        objective="",
        blocks=[
            graph_state.ScriptBlock(
                index=1,
                heading="Главное",
                summary="Краткое содержание",
                key_points=["Основной тезис"],
                facts=facts,
            )
        ],
        key_messages=["Основной тезис"],
        facts=facts,
    )


def _plan_item(graph_state, template_slide_index: int = 1):
    return graph_state.SlidePlanItem(
        template_slide_index=template_slide_index,
        title="Основной тезис",
        content="Кратко раскрыть основной тезис",
        purpose="Показать главное",
        key_message="Основной тезис",
        source_block_indices=[1],
    )


def test_planner_receives_template_examples_and_capacity(service_importer) -> None:
    nodes, _, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[presentation.SlideData(
            index=14,
            placeholders=[presentation.PlaceholderData(
                idx=28,
                placeholder_type="BODY",
                text="Подробная сводка " + "текст " * 100,
                max_length=500,
            )],
        )],
    )
    info = nodes._prepare_slides_info(template)
    assert "Слайд 14" in info
    assert "max_len=500" in info
    assert "Подробная сводка" in info
    assert "текст " * 100 not in info
    assert "не подряд по индексам" in nodes.PLAN_SLIDES_PROMPT


def test_plan_validation_rejects_invalid_indices_duplicates_and_limit(service_importer) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[
            presentation.SlideData(
                index=1,
                layout_type="title",
                placeholders=[presentation.PlaceholderData(idx=0, text="Заголовок")],
            ),
            presentation.SlideData(
                index=2,
                layout_type="bullets",
                placeholders=[presentation.PlaceholderData(idx=0, text="Тезисы")],
            ),
            presentation.SlideData(
                index=3,
                layout_type="bullets",
                placeholders=[presentation.PlaceholderData(idx=0, text="Тезисы")],
            ),
        ]
    )
    plan = graph_state.SlidePlan(
        slides=[
            _plan_item(graph_state, 1),
            _plan_item(graph_state, 1),
            _plan_item(graph_state, 99),
        ]
    )

    issues = nodes._plan_validation_issues(
        plan,
        template,
        _analysis(graph_state),
        2,
        "Основной тезис",
    )

    assert any("разрешено не больше 2" in issue for issue in issues)
    assert any("индексами: 99" in issue for issue in issues)
    assert "template_slide_index должен быть уникальным" in issues


def test_plan_validation_rejects_slide_without_text_placeholders(service_importer) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[presentation.SlideData(index=1, layout_type="image")]
    )
    plan = graph_state.SlidePlan(slides=[_plan_item(graph_state, 1)])

    issues = nodes._plan_validation_issues(
        plan,
        template,
        _analysis(graph_state),
        1,
        "Основной тезис",
    )

    assert "слайды не содержат текстовых placeholder: 1" in issues


def test_strict_user_mapping_requires_mapped_slide_in_plan(service_importer) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[
            presentation.SlideData(
                index=1,
                placeholders=[presentation.PlaceholderData(idx=0)],
            ),
            presentation.SlideData(
                index=2,
                placeholders=[presentation.PlaceholderData(idx=0)],
            ),
        ]
    )
    plan = graph_state.SlidePlan(slides=[_plan_item(graph_state, 1)])

    issues = nodes._plan_validation_issues(
        plan,
        template,
        _analysis(graph_state),
        2,
        "Основной тезис",
        {"2": {"0": "Обязательный текст"}},
        True,
    )

    assert "план не использовал слайды из пользовательской разметки: 2" in issues


def test_invalid_user_mapping_fails_before_llm_call(monkeypatch, service_importer) -> None:
    nodes, graph_state, presentation, request = _load_content_modules(service_importer)
    errors = importlib.import_module("app.errors")
    calls = []

    async def unexpected_generate_json(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("LLM call must not happen")

    monkeypatch.setattr(nodes.llm_client, "generate_json", unexpected_generate_json)
    state = graph_state.ContentGraphState(
        presentation=presentation.PresentationData(
            slides=[
                presentation.SlideData(
                    index=1,
                    placeholders=[presentation.PlaceholderData(idx=0)],
                )
            ]
        ),
        script="Источник",
        user_mapping={"1": {"999": "Неизвестное поле"}},
        settings=request.GenerationSettings(),
    )

    with pytest.raises(errors.UserMappingValidationError, match="неизвестный placeholder"):
        asyncio.run(nodes.analyze_script(state))

    assert calls == []


def test_analysis_prompt_uses_source_and_generation_settings(monkeypatch, service_importer) -> None:
    nodes, graph_state, presentation, request = _load_content_modules(service_importer)
    captured = {}

    async def fake_generate_json(prompt, model, strict=True):
        captured["prompt"] = prompt
        return _analysis(graph_state, ["18%"])

    monkeypatch.setattr(nodes.llm_client, "generate_json", fake_generate_json)
    state = graph_state.ContentGraphState(
        presentation=presentation.PresentationData(),
        script="Выручка выросла на 18%",
        settings=request.GenerationSettings(language="ru", complexity="simple"),
    )

    asyncio.run(nodes.analyze_script(state))

    assert "Выручка выросла на 18%" in captured["prompt"]
    assert "18%" in captured["prompt"]
    assert "язык: ru" in captured["prompt"]
    assert "сложность формулировок: simple" in captured["prompt"]
    assert "Не додумывай" in captured["prompt"]
    assert captured["prompt"].count("<SOURCE_SCRIPT>") == 1
    assert "95%" not in captured["prompt"]


def test_llm_client_uses_validated_runtime_limits(
    monkeypatch,
    service_importer,
) -> None:
    captured = {}

    class FakeChatCompletions:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("LLM_API_TIMEOUT", "37")
    monkeypatch.setenv("LLM_MAX_TOKENS", "7654")

    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    monkeypatch.setattr(llm, "ChatCompletionsClient", FakeChatCompletions)
    llm.LLMClient()

    assert captured["timeout"] == 37
    assert captured["base_url"] == "https://router.huggingface.co/v1"
    assert llm.settings.llm_max_tokens == 7654

    with pytest.raises(ValueError):
        llm.settings.__class__(llm_api_timeout=0)
    with pytest.raises(ValueError):
        llm.settings.__class__(llm_max_tokens=0)


def test_planning_prompt_and_result_respect_max_slides(monkeypatch, service_importer) -> None:
    nodes, graph_state, presentation, request = _load_content_modules(service_importer)
    captured = []

    async def fake_generate_json(prompt, model, strict=True):
        captured.append(prompt)
        slide_count = 3 if len(captured) == 1 else 2
        return model(slides=[_plan_item(graph_state, index) for index in range(1, slide_count + 1)])

    monkeypatch.setattr(nodes.llm_client, "generate_json", fake_generate_json)
    state = graph_state.ContentGraphState(
        presentation=presentation.PresentationData(
            slides=[
                presentation.SlideData(
                    index=1,
                    layout_type="title",
                    placeholders=[presentation.PlaceholderData(idx=0, text="Заголовок")],
                ),
                presentation.SlideData(
                    index=2,
                    layout_type="bullets",
                    placeholders=[presentation.PlaceholderData(idx=0, text="Тезисы")],
                ),
                presentation.SlideData(
                    index=3,
                    layout_type="summary",
                    placeholders=[presentation.PlaceholderData(idx=0, text="Вывод")],
                ),
            ]
        ),
        script="Текст",
        analysis=_analysis(graph_state),
        settings=request.GenerationSettings(max_slides=2, tone="neutral"),
    )

    result = asyncio.run(nodes.plan_slides(state))

    assert len(result["plan"].slides) == 2
    assert "максимальное количество слайдов: 2" in captured[0]
    assert "тон: neutral" in captured[0]
    assert "Один template_slide_index используй не более одного раза" in captured[0]
    assert "Предыдущий результат отклонён проверкой" in captured[1]


def test_generation_prompt_is_grounded_and_schema_has_length_limit(
    monkeypatch,
    service_importer,
) -> None:
    nodes, graph_state, presentation, request = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[
            presentation.SlideData(
                index=1,
                layout_type="title",
                placeholders=[
                    presentation.PlaceholderData(
                        idx=0,
                        name="Title",
                        placeholder_type="TITLE",
                        text="Исходный заголовок",
                        max_length=32,
                    )
                ],
            )
        ]
    )
    plan_item = _plan_item(graph_state)
    plan_item = plan_item.model_copy(update={"key_message": "Выручка выросла на 18%"})
    analysis = graph_state.ScriptAnalysis(
        topic="Результаты квартала",
        audience="",
        objective="",
        facts=["Выручка выросла на 18%"],
        key_messages=["Выручка выросла на 18%"],
        blocks=[
            graph_state.ScriptBlock(
                index=1,
                heading="Рост",
                summary="Рост выручки",
                key_points=["Выручка выросла на 18%"],
                facts=["Выручка выросла на 18%"],
            )
        ],
    )
    captured = {}

    async def fake_generate_json_with_schema(prompt, schema, strict=True):
        captured["prompt"] = prompt
        captured["schema"] = schema
        return {"0": "Выручка выросла на 18%"}

    monkeypatch.setattr(
        nodes.llm_client,
        "generate_json_with_schema",
        fake_generate_json_with_schema,
    )

    _, result = asyncio.run(
        nodes._generate_slide_content(
            template,
            plan_item,
            user_mapping=None,
            issues=["Слайд 1, placeholder Title: текст длиннее максимума"],
            analysis=analysis,
            settings=request.GenerationSettings(tone="concise"),
            source_text="Оригинал: выручка выросла на 18%",
        )
    )

    assert result.placeholders["0"] == "Выручка выросла на 18%"
    assert "Выручка выросла на 18%" in captured["prompt"]
    assert "concise" in captured["prompt"]
    assert "<SOURCE_SCRIPT>\nОригинал: выручка выросла на 18%\n</SOURCE_SCRIPT>" in captured["prompt"]
    assert "текст длиннее максимума" in captured["prompt"]
    assert "не добавляй дефисы" in captured["prompt"]
    assert captured["schema"]["properties"]["0"]["maxLength"] == 32
    assert captured["schema"]["properties"]["0"]["minLength"] == 1
    assert "Каждый placeholder должен содержать непустой текст" in captured["prompt"]


def test_generation_rejects_slide_without_text_placeholders(service_importer) -> None:
    nodes, graph_state, presentation, request = _load_content_modules(service_importer)
    errors = importlib.import_module("app.errors")
    template = presentation.PresentationData(
        slides=[presentation.SlideData(index=1, layout_type="image")]
    )

    with pytest.raises(errors.ContentValidationError, match="не содержит текстовых placeholder"):
        asyncio.run(
            nodes._generate_slide_content(
                template,
                _plan_item(graph_state),
                user_mapping=None,
                issues=[],
                analysis=_analysis(graph_state),
                settings=request.GenerationSettings(),
            )
        )


def test_retry_preserves_valid_slides(monkeypatch, service_importer) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[
            presentation.SlideData(index=1),
            presentation.SlideData(index=2),
        ]
    )
    previous_first_slide = graph_state.GeneratedSlideContent(placeholders={"0": "Готово"})
    state = graph_state.ContentGraphState(
        presentation=template,
        script="Текст",
        plan=graph_state.SlidePlan(
            slides=[
                _plan_item(graph_state, 1),
                _plan_item(graph_state, 2),
            ]
        ),
        content={1: previous_first_slide},
        validation=graph_state.ValidationReport(
            ok=False,
            issues=["Слайд 2: нет сгенерированного контента"],
        ),
    )
    regenerated_indices = []

    async def fake_generate_slide_content(
        presentation_data,
        slide_plan,
        user_mapping,
        issues,
        analysis,
        settings,
        source_text=None,
        feedback=None,
    ):
        assert source_text == "Текст"
        regenerated_indices.append(slide_plan.template_slide_index)
        return (
            slide_plan.template_slide_index,
            graph_state.GeneratedSlideContent(placeholders={"0": "Исправлено"}),
        )

    monkeypatch.setattr(nodes, "_generate_slide_content", fake_generate_slide_content)

    result = asyncio.run(nodes.generate_content(state))

    assert result["content"][1] is previous_first_slide
    assert regenerated_indices == [2]


def test_issue_filter_keeps_slide_numbers_separate(service_importer) -> None:
    nodes, _, _, _ = _load_content_modules(service_importer)
    issues = [
        "Слайд 1: нет сгенерированного контента",
        "Слайд 10: нет сгенерированного контента",
        "Общая ошибка контракта",
    ]

    assert nodes._issues_for_slide(issues, 1) == [
        "Общая ошибка контракта",
        "Слайд 1: нет сгенерированного контента",
    ]


def test_validation_ignores_unplanned_template_slides(service_importer) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[
            presentation.SlideData(
                index=1,
                placeholders=[presentation.PlaceholderData(idx=0, text="Заголовок")],
            ),
            presentation.SlideData(
                index=2,
                placeholders=[presentation.PlaceholderData(idx=0, text="Не выбран")],
            ),
        ]
    )
    content = {
        1: graph_state.GeneratedSlideContent(placeholders={"0": "Готовый заголовок"}),
    }

    report = asyncio.run(nodes.ContentValidator.validate(template, content, {1}))

    assert report.ok is True
    assert report.issues == []


def test_content_validation_rejects_builder_incompatible_keys_and_missing_values(
    service_importer,
) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[
            presentation.SlideData(
                index=1,
                placeholders=[
                    presentation.PlaceholderData(idx=0),
                    presentation.PlaceholderData(idx=1),
                ],
            )
        ]
    )
    content = {
        1: graph_state.GeneratedSlideContent(
            placeholders={"0": "Готовый заголовок", "999": "Лишнее поле"}
        )
    }

    report = asyncio.run(nodes.ContentValidator.validate(template, content, {1}))

    assert report.ok is False
    assert any("неизвестные placeholders: 999" in issue for issue in report.issues)
    assert any("placeholder 1: не заполнен" in issue for issue in report.issues)


@pytest.mark.parametrize("placeholder_type", ["OBJECT", "VERTICAL_BODY"])
def test_content_validation_rejects_manual_markers_in_list_placeholder(
    placeholder_type: str,
    service_importer,
) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[
            presentation.SlideData(
                index=1,
                placeholders=[
                    presentation.PlaceholderData(
                        idx=1,
                        placeholder_type=placeholder_type,
                    )
                ],
            )
        ]
    )
    content = {
        1: graph_state.GeneratedSlideContent(
            placeholders={"1": "- Первый пункт\n- Второй пункт"}
        )
    }

    report = asyncio.run(nodes.ContentValidator.validate(template, content, {1}))

    assert report.ok is False
    assert any("ручные маркеры списка" in issue for issue in report.issues)


def test_manual_list_marker_detection_supports_multidigit_numbering(
    service_importer,
) -> None:
    validation = service_importer(CONTENT_SERVICE_ROOT, "app.utils.validation")

    assert validation.contains_manual_list_markers("10. Десятый пункт") is True
    assert validation.contains_manual_list_markers("+ Markdown-пункт") is True
    assert validation.contains_manual_list_markers("Рост составил 10.5%") is False


def test_content_validation_rejects_blank_list_items(service_importer) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[
            presentation.SlideData(
                index=1,
                placeholders=[
                    presentation.PlaceholderData(
                        idx=1,
                        placeholder_type="OBJECT",
                    )
                ],
            )
        ]
    )
    content = {
        1: graph_state.GeneratedSlideContent(
            placeholders={"1": "Первый пункт\n\nВторой пункт"}
        )
    }

    report = asyncio.run(nodes.ContentValidator.validate(template, content, {1}))

    assert report.ok is False
    assert any("список содержит пустые строки" in issue for issue in report.issues)


@pytest.mark.parametrize(
    ("mapping_value", "expected_message"),
    [
        ("- Первый пункт\n- Второй пункт", "ручные маркеры списка"),
        ("Первый пункт\n\nВторой пункт", "пустые строки"),
    ],
)
def test_invalid_list_user_mapping_fails_before_llm_call(
    mapping_value: str,
    expected_message: str,
    monkeypatch,
    service_importer,
) -> None:
    nodes, graph_state, presentation, request = _load_content_modules(service_importer)
    errors = importlib.import_module("app.errors")
    calls = []

    async def unexpected_generate_json(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("LLM call must not happen")

    monkeypatch.setattr(nodes.llm_client, "generate_json", unexpected_generate_json)
    state = graph_state.ContentGraphState(
        presentation=presentation.PresentationData(
            slides=[
                presentation.SlideData(
                    index=1,
                    placeholders=[
                        presentation.PlaceholderData(
                            idx=1,
                            placeholder_type="OBJECT",
                        )
                    ],
                )
            ]
        ),
        script="Источник",
        user_mapping={"1": {"1": mapping_value}},
        settings=request.GenerationSettings(),
    )

    with pytest.raises(errors.UserMappingValidationError, match=expected_message):
        asyncio.run(nodes.analyze_script(state))

    assert calls == []


def test_llm_retries_malformed_json_instead_of_returning_empty_model(
    monkeypatch,
    service_importer,
) -> None:
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    graph_state = importlib.import_module("app.models.graph_state")
    responses = iter(
        [
            "{broken json",
            """{
                "topic": "Рост",
                "audience": "",
                "objective": "",
                "blocks": [{
                    "index": 1,
                    "heading": "Результат",
                    "summary": "Выручка выросла на 18%",
                    "key_points": ["Рост 18%"],
                    "facts": ["18%"]
                }],
                "key_messages": ["Рост 18%"],
                "facts": ["18%"]
            }""",
        ]
    )
    calls = []

    def fake_chat(_chat):
        calls.append(True)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))]
        )

    monkeypatch.setattr(llm.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.llm_client.client, "chat", fake_chat)

    result = asyncio.run(llm.llm_client.generate_json("Источник", graph_state.ScriptAnalysis))

    assert result.topic == "Рост"
    assert len(calls) == 2


def test_llm_raises_typed_error_after_invalid_responses(monkeypatch, service_importer) -> None:
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    errors = importlib.import_module("app.errors")
    graph_state = importlib.import_module("app.models.graph_state")

    def fake_chat(_chat):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))]
        )

    monkeypatch.setattr(llm.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.llm_client.client, "chat", fake_chat)

    with pytest.raises(errors.LLMGenerationError, match="remained invalid"):
        asyncio.run(llm.llm_client.generate_json("Источник", graph_state.ScriptAnalysis))


def test_llm_fails_before_network_call_without_api_key(monkeypatch, service_importer) -> None:
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    errors = importlib.import_module("app.errors")
    graph_state = importlib.import_module("app.models.graph_state")
    calls = []

    def fake_chat(_chat):
        calls.append(True)
        raise AssertionError("network call must not happen")

    monkeypatch.setattr(llm.settings, "llm_api_key", "")
    monkeypatch.setattr(llm.llm_client.client, "chat", fake_chat)

    with pytest.raises(errors.LLMGenerationError, match="LLM_API_KEY не настроен"):
        asyncio.run(llm.llm_client.generate_json("Источник", graph_state.ScriptAnalysis))

    assert calls == []


def test_llm_recovers_code_fence_and_trailing_commas(service_importer) -> None:
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")

    parsed = llm.LLMClient._parse_json_object(
        """```json
        {"slides": [{"title": "Итог",}],}
        ```"""
    )

    assert parsed == {"slides": [{"title": "Итог"}]}


def test_llm_recovers_noise_before_json_line_tokens(service_importer) -> None:
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")

    parsed = llm.LLMClient._parse_json_object(
        """{
        noise "blocks": [
            garbage {"index": 1, "facts": [
                كلمة "87% участников",
                marker "6 минут"
            ]},
            trailing ]
        suffix }"""
    )

    assert parsed == {
        "blocks": [{"index": 1, "facts": ["87% участников", "6 минут"]}]
    }


def test_fact_tokens_do_not_capture_line_breaks(service_importer) -> None:
    grounding = service_importer(CONTENT_SERVICE_ROOT, "app.utils.grounding")

    assert grounding.extract_fact_tokens("2026\n87% участников") == {"2026", "87%"}


def test_grounding_rejects_derived_claim_absent_from_source(service_importer) -> None:
    grounding = service_importer(CONTENT_SERVICE_ROOT, "app.utils.grounding")

    unsupported = grounding.find_unsupported_claim_markers(
        "Первый этап охватил 120 человек, следующий охватит 300 человек",
        "Охват увеличится втрое",
    )

    assert unsupported == {"втрое"}


def test_content_validation_checks_source_facts(service_importer) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(slides=[presentation.SlideData(index=1)])
    content = {
        1: graph_state.GeneratedSlideContent(
            placeholders={"0": "Выручка выросла на 21% в 2025 году"}
        )
    }

    report = asyncio.run(
        nodes.ContentValidator.validate(
            template,
            content,
            {1},
            "Выручка выросла на 18% в 2026 году",
        )
    )

    assert report.ok is False
    assert any("18%" in issue and "2026" in issue for issue in report.issues)
    assert any("21%" in issue and "2025" in issue for issue in report.issues)


def test_slide_grounding_checks_its_planned_facts(service_importer) -> None:
    nodes, graph_state, _, _ = _load_content_modules(service_importer)
    plan_item = _plan_item(graph_state).model_copy(
        update={
            "content": "Показать 87% и 6 минут",
            "key_message": "87% справились за 6 минут",
        }
    )
    analysis = _analysis(graph_state, ["87%", "6 минут"])

    issues = nodes._slide_content_grounding_issues(
        {"0": "Самостоятельно справились 8 участников"},
        plan_item,
        analysis,
    )

    assert any("6" in issue and "87%" in issue for issue in issues)
    assert any("8" in issue for issue in issues)


def test_graph_raises_after_content_retry_budget(service_importer) -> None:
    builder = service_importer(CONTENT_SERVICE_ROOT, "app.graph.builder")
    errors = importlib.import_module("app.errors")
    graph_state = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    config = importlib.import_module("app.config")
    state = graph_state.ContentGraphState(
        presentation=presentation.PresentationData(),
        script="Источник",
        retries=config.settings.content_validation_retries + 1,
        validation=graph_state.ValidationReport(ok=False, issues=["Факт потерян"]),
    )

    with pytest.raises(errors.ContentValidationError, match="Факт потерян"):
        builder._should_retry(state)
