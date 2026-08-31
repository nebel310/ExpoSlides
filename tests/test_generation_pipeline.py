from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTENT_SERVICE_ROOT = REPOSITORY_ROOT / "services" / "content-service"


def _load_content_modules(service_importer):
    nodes = service_importer(CONTENT_SERVICE_ROOT, "app.graph.nodes")
    graph_state = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    request = importlib.import_module("app.models.request")
    return nodes, graph_state, presentation, request


def test_plan_normalization_enforces_unique_indices_and_limit(service_importer) -> None:
    nodes, graph_state, presentation, _ = _load_content_modules(service_importer)
    template = presentation.PresentationData(
        slides=[
            presentation.SlideData(index=1, layout_type="title"),
            presentation.SlideData(index=2, layout_type="bullets"),
            presentation.SlideData(index=3, layout_type="bullets"),
        ]
    )
    plan = graph_state.SlidePlan(
        slides=[
            graph_state.SlidePlanItem(template_slide_index=1, key_message="Контекст"),
            graph_state.SlidePlanItem(template_slide_index=1, key_message="Результат"),
            graph_state.SlidePlanItem(template_slide_index=99, key_message="Вывод"),
        ]
    )

    normalized = nodes._normalize_plan(plan, template, max_slides=2)

    assert [item.template_slide_index for item in normalized.slides] == [1, 2]


def test_analysis_prompt_uses_source_and_generation_settings(monkeypatch, service_importer) -> None:
    nodes, graph_state, presentation, request = _load_content_modules(service_importer)
    captured = {}

    async def fake_generate_json(prompt, model, strict=True):
        captured["prompt"] = prompt
        return model()

    monkeypatch.setattr(nodes.llm_client, "generate_json", fake_generate_json)
    state = graph_state.ContentGraphState(
        presentation=presentation.PresentationData(),
        script="Выручка выросла на 18%",
        settings=request.GenerationSettings(language="ru", complexity="simple"),
    )

    asyncio.run(nodes.analyze_script(state))

    assert "Выручка выросла на 18%" in captured["prompt"]
    assert "язык: ru" in captured["prompt"]
    assert "сложность формулировок: simple" in captured["prompt"]
    assert "Не додумывай" in captured["prompt"]


def test_planning_prompt_and_result_respect_max_slides(monkeypatch, service_importer) -> None:
    nodes, graph_state, presentation, request = _load_content_modules(service_importer)
    captured = {}

    async def fake_generate_json(prompt, model, strict=True):
        captured["prompt"] = prompt
        return model(
            slides=[
                graph_state.SlidePlanItem(template_slide_index=1),
                graph_state.SlidePlanItem(template_slide_index=2),
                graph_state.SlidePlanItem(template_slide_index=3),
            ]
        )

    monkeypatch.setattr(nodes.llm_client, "generate_json", fake_generate_json)
    state = graph_state.ContentGraphState(
        presentation=presentation.PresentationData(
            slides=[
                presentation.SlideData(index=1, layout_type="title"),
                presentation.SlideData(index=2, layout_type="bullets"),
                presentation.SlideData(index=3, layout_type="summary"),
            ]
        ),
        script="Текст",
        analysis=graph_state.ScriptAnalysis(key_messages=["Первое", "Второе"]),
        settings=request.GenerationSettings(max_slides=2, tone="neutral"),
    )

    result = asyncio.run(nodes.plan_slides(state))

    assert len(result["plan"].slides) == 2
    assert "максимальное количество слайдов: 2" in captured["prompt"]
    assert "тон: neutral" in captured["prompt"]
    assert "Один template_slide_index используй не более одного раза" in captured["prompt"]


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
    plan_item = graph_state.SlidePlanItem(
        template_slide_index=1,
        key_message="Выручка выросла на 18%",
        source_block_indices=[1],
    )
    analysis = graph_state.ScriptAnalysis(
        topic="Результаты квартала",
        facts=["Выручка выросла на 18%"],
        blocks=[
            graph_state.ScriptBlock(
                index=1,
                summary="Рост выручки",
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
        )
    )

    assert result.placeholders["0"] == "Выручка выросла на 18%"
    assert "Выручка выросла на 18%" in captured["prompt"]
    assert "concise" in captured["prompt"]
    assert "текст длиннее максимума" in captured["prompt"]
    assert captured["schema"]["properties"]["0"]["maxLength"] == 32


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
                graph_state.SlidePlanItem(template_slide_index=1),
                graph_state.SlidePlanItem(template_slide_index=2),
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
    ):
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
