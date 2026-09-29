"""Сопоставимая оценка видимой полноты без внешних моделей."""

import json
from pathlib import Path

from evals.score import score_response
from exposlides.design_audit import audit_deck
from exposlides.design_models import DeckPlan, PlacedBlock, SlideInstance, TextStyle
from tests.test_design_workflow import profile


def test_notes_do_not_replace_visible_facts_in_density_case():
    cases = json.loads((Path(__file__).parents[1] / 'evals/generation_cases.json').read_text(
        encoding='utf-8',
    ))
    case = next(item for item in cases if item['id'] == 'agent-explanation-density')
    sparse = {'content': {'1': {'placeholders': {
        '0': 'Управление агентом', '1': case['required_messages'][0],
    }, 'notes': case['script']}}}
    expanded = {'content': {'1': {'placeholders': {
        str(index): text for index, text in enumerate(case['required_messages'])
    }}}}

    before, after = score_response(case, sparse), score_response(case, expanded)

    assert before['message_recall'] == 0.25
    assert len(before['missing_messages']) == 3
    assert after['message_recall'] == after['fact_recall'] == 1
    assert not after['semantic_issues']
    assert before['score'] < after['score'] == 100


def test_supported_explanation_is_not_automatically_a_long_bullet():
    template = profile()
    body = PlacedBlock(
        id='body', kind='text', style=TextStyle(size=20),
        box=template.patterns[0].content_box,
        items=['LangGraph предоставляет рантайм для долговременного выполнения и пауз, '
               'во время которых человек может вмешаться в цикл агента. '
               'Это важно для критичных приложений.'],
    )
    plan = DeckPlan(
        variant_id='story', name='Story', description='', width=template.width,
        height=template.height, slides=[SlideInstance(
            id='slide-1', story_slide_id='s1', source_slide_index=1, blocks=[body],
        )],
    )

    assert not any(issue.rule == 'long_bullet' for issue in audit_deck(plan, template).issues)
    body.items = [body.items[0] * 3]
    assert any(issue.rule == 'long_bullet' for issue in audit_deck(plan, template).issues)
