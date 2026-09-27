# Проверка реализации — 27 сентября 2026 года

Выполнен реальный файловый pipeline в режиме **extractive** на четырёх
**синтетических** шаблонах с LibreOffice и Poppler. Все четыре случая прошли
структурные проверки. Созданы 12 комплектов PPTX/HTML/PDF и 138 PNG-рендеров.

Это проверка реализации и экспорта. Она не измеряет качество живой Qwen,
инференс VK, контекстуальную оценку VLM или генерацию изображений FLUX.
Шаблоны организатора в этом прогоне не использовались.

## Точный запуск

Рабочий каталог:
`/Users/aleksemanov/.codex/worktrees/vk-tech-completion/ExpoSlides`.

```bash
UV_CACHE_DIR=/tmp/exposlides-audit-uv-cache uv run --no-sync python -m scripts.benchmark_designer --output-dir /tmp/exposlides-designer-benchmark-20260927-accepted-final
```

Код завершения: **0**. Python: **3.12.12**. Платформа:
`macOS-26.3.1-arm64-arm-64bit`. Зависимости взяты из подготовленного uv-окружения;
хеш `uv.lock` сохранён в отчёте. При повторении нужно выбрать новый или пустой
выходной каталог. Скорость другого компьютера может отличаться.

## Результаты

| Шаблон | Слайдов в варианте | Вариантов | Pipeline всех вариантов, с | Результат |
| --- | --- | --- | --- | --- |
| `ordinary_textboxes` | 12 | 3 | 7.909 | passed |
| `dark` | 12 | 3 | 7.167 | passed |
| `grouped_protected` | 12 | 3 | 7.333 | passed |
| `synthetic_holdout` | 10 | 3 | 7.327 | passed |

Суммарное время четырёх случаев вместе с проверками: **29.899 секунды**.
Каждый отдельный случай укладывается в заданный предел 300 секунд. Модельного
инференса в это время нет; измерение не доказывает скорость режима `llm`.

Подтверждено исполняемыми проверками:

- сохранённый PPTX повторно открывается и содержит нужное число слайдов;
- исходные заголовки, абзацы и наборы данных сохраняются во всех вариантах;
- таблицы остаются таблицами; графики содержат исходные числа и встроенную книгу;
- схемы состоят из редактируемых фигур с исходными подписями;
- исходный шаблон не меняется; в ZIP-контейнере нет дублирующихся имён частей;
- PDF и HTML созданы, число PNG совпадает с числом слайдов;
- для каждой позиции слайда три варианта имеют разные SHA-256 PNG.

Все 12 отчётов детерминированного аудита содержат **0 ошибок и 0 предупреждений**.
Контекстуальный статус каждого варианта — **`not_run`**. Запросов к API этот
сценарий не включает: `api_calls_requested=false`. Разные PNG и отсутствие
замечаний детерминированного аудита не доказывают дизайнерское качество.

## Зафиксированная реализация и настройки

Отчёт сохраняет **50 SHA-256** файлов реализации и lock-файла.
Повторная проверка после прогона дала
`implementation_changed_during_run=false`.

В каждом из четырёх manifest одинаковый набор versioned resources:
`config/models.toml`, `config/run.example.toml`, `config/skills.toml`,
`agents/designer.toml` и три
внешних промпта дизайнера. Полные manifest приведены ниже. В частности,
пороговые значения аудита реально читались из `config/skills.toml` версии 1.0.0.
Каждый manifest также содержит `request_sha256` полного запроса с datasets и
`story_model: null`, поскольку этот прогон не вызывает модель. В режиме `llm`
адаптер сохраняет безопасный `story-provenance.json` с отправленным alias;
этот контракт проверен отдельными CLI-тестами с fake generation.

Проверка заметок докладчика включена в исполняемый `validate_story`: она
отклоняет обнаруженные неподтверждённые числа и подмены распознанных фактов.
Заметки не дают зачёта покрытия видимого содержания. Специальные отрицательные
сценарии заметок находятся в `tests/test_design_workflow.py`; сам benchmark
генерирует историю локально и не имитирует ошибочные ответы LLM.

TOML launcher `exposlides/run_config.py` входит в снимок исходников, а пример
`config/run.example.toml` — в manifest. Сам benchmark вызывает `DesignPipeline`
напрямую и не проверяет launcher; его отдельные unit-тесты находятся в
`tests/test_design_run_config.py`. Их результаты и полный pytest относятся к
общему отчёту проверки проекта, а не к результату команды benchmark выше.
Отдельная браузерная демонстрация на пяти слайдах также не является проверкой
официальных материалов организатора и не входит в этот benchmark.

## Дополнительные проверки проекта

Полные проверки выполнены отдельно от команды benchmark; результаты также
зафиксированы в [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

| Команда из корня | Результат |
| --- | --- |
| `uv run --offline pytest --tb=short` | **1 230 passed**, 23.47 с; одно StarletteDeprecationWarning |
| `uv run --offline ruff check .` | Все проверки пройдены |
| `uv lock --check` | Lock согласован, 109 пакетов |
| `git diff --check` | Без ошибок |

Все модельные вызовы автоматических тестов подменяются. Эти результаты не
подтверждают доступность живого VK endpoint или качество ответов модели.

## Артефакты и архив отчёта

Рабочие бинарные результаты находятся в
`/tmp/exposlides-designer-benchmark-20260927-accepted-final/`.
Для каждого случая каталог `job/variants/<story|evidence|cards>/1/` содержит
`presentation.pptx`, `presentation.pdf`, `presentation.html`, `plan.json`,
`audit.json`, `exports.json` и изображения. В `job/` сохранены request,
template profile, story и manifest; входные шаблон и brief лежат в каталоге случая.

Бинарные артефакты не добавлены в Git. Полный JSON-отчёт и manifest встроены
в этот Markdown, чтобы сохранить результаты и контрольные суммы независимо
от срока жизни временного каталога.

SHA-256 исходных байтов `benchmark-report.json`:
`1b7678046a34c77cd8f6096f6dac20b2265c765a1c439b8e81e5b65618a2c50c`.
Исходный JSON не имеет завершающего перевода строки.

<details>
<summary>Полный benchmark-report.json</summary>

```json
{
  "schema_version": "1.0",
  "python": "3.12.12",
  "platform": "macOS-26.3.1-arm64-arm-64bit",
  "mode": "extractive",
  "api_calls_requested": false,
  "implementation_sha256": {
    "scripts/benchmark_designer.py": "394906ddc1a3656df30c74ddc5f993e5aa621ee5a1ae9ff63574be22272604e6",
    "uv.lock": "5bd8742cf304fae4b49093abce597391fe6b76c5bd1584737d6bad05b1f84670",
    "exposlides/__init__.py": "1124198621e64788d6f3a7a8b22ea923365812cd9ce5968798a4f070d64adced",
    "exposlides/__main__.py": "0cdf358dfc840207ffccc7f28689566508675c256ba002d29d467eebf5ef0974",
    "exposlides/cli.py": "880dfaf6caca7f0732980b0de0fd409750c5ff00b77e1401e701b4287456889a",
    "exposlides/design_audit.py": "ea277ab961f178b668c92971757419d85152dcd2cf1e03fc31ba68a9e5559298",
    "exposlides/design_builder.py": "f25d20334f9c59911d62b42a6c01c9e5c524df2d4e24a9fc6cdb9c8cadafc25b",
    "exposlides/design_cli.py": "7b768303ffcb931966b5894916e1120b9a07e8c8d846f8a12303d6c9a1758998",
    "exposlides/design_content.py": "b6d1ec33f9f9ff578f05fbea1f3b5ca9c1b5217df4d3370e71023e899577f1b6",
    "exposlides/design_export.py": "4c5a1ce1e55a249be27f9a218d3f6a77046c2fa4ada880f5ede70c73adddcc6c",
    "exposlides/design_geometry.py": "4220ba9210d7a2b6f53e8e4da10e869a15aa0440e93aa45b54e9e703154804e7",
    "exposlides/design_layout.py": "f72527ff587a0b279f1a0b504cf78616a5e4e1457b212a62479947f8523396eb",
    "exposlides/design_models.py": "402311e9941f1ae7250141fde804fdc5aa8f4550d393261bcd41ad8a2022ed56",
    "exposlides/design_pipeline.py": "48457077b45731938aa377894454f49315d0fe39bd3159d46cb1dcd93b21434f",
    "exposlides/design_pptx_parts.py": "60f0bebab30c72453699984841ea1a22ffb8547c70663f5e1ac4492a73802268",
    "exposlides/design_saved_audit.py": "25aed726ad3499bd681da06684b254fff3fa3d3cddfd4c51418e0e7fa33904ef",
    "exposlides/design_smartart.py": "2d3a8baf716f151f42b107112da147c579efa1cfb1b5233fd20fe3448bc5b95c",
    "exposlides/file_storage.py": "a687227d65a7e4346f713e57bb2b0879d3e7e03e5173dc8b7efa44be5435b24f",
    "exposlides/preview.py": "5bececa4f56e26f696835affbeac25de3cdf6e83c5857d2db0385d2a43f14e7e",
    "exposlides/run_config.py": "35c5a33a1f5b55d0c582f8c9c3e97f5594769f558b26a9aacc093e579f675ac7",
    "exposlides/studio.py": "669feb1da6bc5ca04853e490683efa5b9ebc47d5a16b188bc22a7762038b6f5d",
    "exposlides/template_profile.py": "b01a2e680c1695bcb4d62d7ee6a8ee426e29ee33fbaf74e4cc84e8f2f17fc735",
    "exposlides/web.py": "635658f6af0e4cca62626e9185f325bb372aaf7ea180e6493c20775fb88cede0",
    "exposlides/web_catalog.py": "dcc457f58f6c3a2770b7f72dc905448e56a73fff34f018c8726c51030c1321e1",
    "services/parsing-service/app/config.py": "6ddd4fdf2b09d1c92cc85adcadb5df9c21e2f7fa1d3c3c8078d8085e33ab044e",
    "services/parsing-service/app/grpc/file_service_client.py": "c4347a7191076a64f12662b6c47a9784646a5e8049f68947972926a492257b72",
    "services/parsing-service/app/grpc/server.py": "cbfbdee3f7de8c706f2ef26a6dc1be0b7a78a9bc9b95772a547aba7c5da6e293",
    "services/parsing-service/app/kafka/consumer.py": "84c4ebd1c6b1b2533c5e406365ec71cdb6acff98bcb7f9e864d5cefc63778f05",
    "services/parsing-service/app/kafka/producer.py": "4d24ece91caf3d40354c9335b17930cdc7ad0b47961bac882b88f4eeaad2c3b0",
    "services/parsing-service/app/kafka/schemas.py": "245d58165ff3b4187da32b0191f3e4849acff2ee2281ec607e514fbd377c68e8",
    "services/parsing-service/app/main.py": "a34a41ba7e9cdc1e9ea6161f8150be2257309bc275fc2ab99a3a9ff9e4f58f02",
    "services/parsing-service/app/models/legacy_presentation.py": "b58890dd2ec70536ff8bed476d147bd221f90b8a752a955effe43972837b15ee",
    "services/parsing-service/app/models/presentation.py": "b03d9eecafd184318ef36bbd5fd043ec8956632b4480543ec3b826b474bd661c",
    "services/parsing-service/app/parsers/base.py": "65346c4208475eb285c9196ae52fa40d7146a1653e1ac1b167218b97c66038b4",
    "services/parsing-service/app/parsers/pptx/__init__.py": "da07c29a153ea26535b52acc98d428ce8eafd6365a6ca2b247d7b42ae1de45f4",
    "services/parsing-service/app/parsers/pptx/assets.py": "b094a3f5b31ee5da9b3f462474a2662b37c183ab30a4ee1184c792b06db3d735",
    "services/parsing-service/app/parsers/pptx/charts.py": "2a6bd179474e7a536cbe73752423912e64cae4d3ef3236fd04eafc4a52a3e0bf",
    "services/parsing-service/app/parsers/pptx/geometry.py": "4e0dfae79eec81cb0ee705a2f83040d834fe086f938144e5468ed0b97502b672",
    "services/parsing-service/app/parsers/pptx/helpers.py": "adf787cd7fb8a96bbf2a5c8885bcba19170b938fc4340aff57ac5409d4e97b7e",
    "services/parsing-service/app/parsers/pptx/parser.py": "253ce92229e4b7ee237af075fc5d1cca925e29133a642811f1997a4c2481f553",
    "services/parsing-service/app/parsers/pptx/shapes.py": "7d9281b619e4048e6920455ad5641c6ff37f9e101ea26ed048de012dec996dbb",
    "services/parsing-service/app/parsers/pptx/smartart.py": "bcb31dd65313135dabe9cb0e836807a0c97de5322793c487c6388b8f01938624",
    "services/parsing-service/app/parsers/pptx/tables.py": "94f77267e2ca29fff1db2de458c5fe9217061d208ade717247fd1ad41982d159",
    "services/parsing-service/app/parsers/pptx/text.py": "73d31b52bbf1becf3c33a87b7d6ed3b5abe700ca73b36ffeed9a4b2967b4de17",
    "services/parsing-service/app/parsers/pptx/tokens.py": "22e7f9aa0fa7b0f912bab7c807c112f42bac94947becab3541d96ccb6c357aab",
    "services/parsing-service/app/parsers/pptx_parser.py": "b490696af501bcfc84aa88f73cf1fe27f3f4a9cfab3f5851b9efe9f604a71934",
    "services/parsing-service/app/parsers/text_style.py": "a51ec14651cc7a10cedb6460eed35816e986e715992e0f836fade249a75eadaf",
    "services/parsing-service/app/services/parser_pipeline.py": "ccd20b12a5229b86b9decec3be76335f2b3a0ebdda1838b68cbe394d523caefd",
    "services/parsing-service/app/utils/file_utils.py": "7b8f37cb9f902e94b960a8d2ac38c54062caf4ecce85e7a96497ecd8894215f5",
    "services/content-service/app/utils/fact_grounding.py": "f760d64313c72af1d7a6af5786158ff0394f93a3a773060918f1e05149dd4800"
  },
  "implementation_changed_during_run": false,
  "seconds": 29.899,
  "cases": [
    {
      "case": "ordinary_textboxes",
      "status": "passed",
      "slide_count": 12,
      "pipeline_seconds": 7.909,
      "template_sha256": "1453b7b66b88259fcf0e5996d7c6a5bd0e3b6034ce7493c9b694dcbf2433c229",
      "distinct_variants_per_slide": [
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true
      ],
      "variants": [
        {
          "id": "story",
          "slide_count": 12,
          "native_objects": {
            "text": 24,
            "chart": 1,
            "process": 1,
            "table": 1
          },
          "png_sha256": [
            "fd28a8b14ca2e3984d763bfb562f74e4be3276172f29144d1a6a7fd1a8c7ba80",
            "26dc5dfb6ec463de65a917910d477d74e5e1a557733254a63228077d7b7c5ad8",
            "42ad99a7307094fbf79ef1f8a8fb2fbf73963d124163917d29fe3fdd1aeaef40",
            "02d0005fe2749ccedfed0c1289ec5faf6e4a8b4231ecb89b2cd12978d79953c5",
            "582067a198a7de7980afbb920f2360d65a1dc39da6fb6a8fa573431ea59a7584",
            "a3b26c0f79463a04a4bfb15ccebd7bb5709f49b6ad15c0e30055f43d4480bb8b",
            "a845c8c9181a44a900849ce6d875ac27718a716f2c32cec2327fc88463b2a67d",
            "428fa19275e6fb4253fa2e57a4c6fb417aa77dd0ab7e59c80899dbdc8ebe820a",
            "726e5f0c31a1860b75bc72b990b4ef8dff30bce27aa9cf6d88ecee3d941f6373",
            "cb955a4c96cd647f6d12f14d06bc776d731c17bd3657b90bedc5383156e4d662",
            "f794e66d6e444092d84c2c32e001aefac12d9f035c27fe59e0703684273b92d2",
            "23e9522721db92009a32ea25baae8dae2213961e1343d03d97111f799beda97a"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/ordinary_textboxes/job/variants/story/1"
        },
        {
          "id": "evidence",
          "slide_count": 12,
          "native_objects": {
            "text": 37,
            "table": 2,
            "process": 1
          },
          "png_sha256": [
            "a3b5fbb7d9d4f2e949c60affc9e236efe08ee410656e12a1ff61aac9a0cc32ee",
            "a7eda056f9e4f6f4b4f751f524f58750e99ac0193630ed7a638734e9d3d5e1eb",
            "3d8fe16716a1a80f80f01b6fcfa426fee28a2c715bea663fe6b9fedc3340be83",
            "241a9c223d657d729c577fe566fe78f762780e6ac3380a63cac0b5efbf34f25c",
            "90f832b046682688cca983f10a92c5dde6cb0f39a56c7e97957ce36e186b1b09",
            "7dcdce6df8944b7753ab88650b682e02e140115d86a4dd8b810e4055b3b02625",
            "4e78eb1f5fa257cd5808e2ef444f1fac6cad1fd0346913cc78a7ce479f4db5d3",
            "23f0c6cbcd798c0907d46df37325c5c6b8719255d94dd6cfe400b8c8e9d071c2",
            "e5e065b53c21ffc679111f27e1c7d1c0c5aa06ee0232f84957448889a9203c47",
            "a811a012fa763eb340f93185c94ba2b840840082471e58796b8a602e78911c1a",
            "97cb3f8d0ef2b2d46675f98e4482c8c54e3a8de9a1940ce35f5de2ff721b758c",
            "42d57a5c3e28109735a0debcdd0a0e40861ffcea41066a055c8b910771cd5bc0"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/ordinary_textboxes/job/variants/evidence/1"
        },
        {
          "id": "cards",
          "slide_count": 12,
          "native_objects": {
            "text": 37,
            "chart": 1,
            "process": 1,
            "table": 1
          },
          "png_sha256": [
            "5e0a4ac047e2a276a06f79e28fa5804a8afb69b04a069e0fb51ce25af83d4e05",
            "c2d6cf3d8a73f37419a2c7d0fb66aeb2883f33de21e685cd9d74bd7f0f9f8631",
            "20600210b9c6ebd19dfd16088083a46bd17d7f64413a5ba9e1fe2bfcce585d6e",
            "09c6540852407efac5b9d825e7f96b044124b35d615e2ad8756371e5f6d57f31",
            "4d2273d34e4ef607f512fa05f041769fc0c2c2a08352171efcf44f89e4227b23",
            "b25e9410e04dfad36b6f0dce479daa970186a8da09b2372761b027d0a91e8223",
            "ce4ee9767b0de0eddbf90b2b5c0e3ed2f5640d61926edd824528442bfed4c342",
            "df0d5d0f9406796180ad23dd131993798347323271cd961888cb7a1d6ebd269a",
            "cc6930de262331b609e0f5e850859ba251385f2b5e63eeb4dffebe2cb0b73922",
            "528d0dd6e36b40c57028f62775643990932147e48208bdf5dcea0988dd0affe4",
            "85610a47bb91c6c5a0994fbf39f2a4238af01aec102f1cfe792aed7cf46ba82a",
            "3f63dd3f2633358afd27654db32855c0baaf465d9a82a2442a34d82be0f30be2"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/ordinary_textboxes/job/variants/cards/1"
        }
      ],
      "claim_scope": "synthetic extractive pipeline; no live model or official template evaluation"
    },
    {
      "case": "dark",
      "status": "passed",
      "slide_count": 12,
      "pipeline_seconds": 7.167,
      "template_sha256": "8992cbc81b5a911d97e939acccdb7b036c2a0ce187c9d9be22150448ea5860c5",
      "distinct_variants_per_slide": [
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true
      ],
      "variants": [
        {
          "id": "story",
          "slide_count": 12,
          "native_objects": {
            "text": 24,
            "chart": 1,
            "process": 1,
            "table": 1
          },
          "png_sha256": [
            "1407c159a4cc045edcc9792a525d39e3e8b0e2a944c755fc0265767a92f0b827",
            "07621402ef58d21eb6d0071e3efdbe4b30bb3ca39478e6008a26e04dc68b198b",
            "2e04247d3ea91dd633ac379cc5446f1f7823c2c52cf1181f66136a3fd23d3786",
            "6c6aea4cca5f52db7165b2ada90bf0682e5407aa62a5fc2b2f1dee6603f7bdaf",
            "9e075249df56a68ffbacf43292d4c5c25b8f4a1a549f970a93588021ae3a8f1a",
            "d9994ef6cb6b18122d148f6d2e94ad7e23c4fb2664dc0814d04adf60cd526142",
            "77a2285a788c6161b31c5dd8e8852d1a1096d28e94ebfc0f4fcb5c821e929054",
            "ef5f40da21606a974acaf1a4a74b05e423b99f088abb47c517f4b35bcd1ce91e",
            "93f9b7c1b3743913e7051c5e33f37099598a23586a6851e8e524b3917bdf0719",
            "9c6c73a4e2c20d8937e1bd38b0675163127fcc59d6a0cb91daa30a1db179db71",
            "5a0e9f4d4628ae3098c82c372fb76b5838036e1c61d8a98b8597cb98c9433ea6",
            "ea879929260c7a43d47f474fafba5d78e90b00430264516f2b9dc5080cc037bb"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/dark/job/variants/story/1"
        },
        {
          "id": "evidence",
          "slide_count": 12,
          "native_objects": {
            "text": 37,
            "table": 2,
            "process": 1
          },
          "png_sha256": [
            "660a9d25757700e25e40a2eb7c27250b681c7ae6e33b77271574e325204356f8",
            "ec90b6f63bd63fb8cbed938636d8f1a78ba8b85a860093d888b899297ae357c4",
            "78ab346c7f26caaa74843c022a7f5cf416cf3d534b05ca025956b67c4ea7d6c4",
            "1d4b975f6823d38ee78600e15d2a1a06e399ad734cf33e6bcf423a2167b1ff56",
            "8f402755c58aee405ca344494b3404a7f2ce77daad2cec45dc5084f959d42a54",
            "d90cd766e93225c19bc898ff8cad6bd5c6a2023aef3dd4649116dab722d96cd7",
            "88816232c2743e48cc4898f0fa1ea31087e1c28aac94644adee518fa36eb6ea9",
            "ebd5da727094864d125ffdc380bde5cbbe195d093fe5a000c5095c4136df6cc1",
            "da1485dba860eed5f2e24312edfd12b62ae59e4ed0484dc4d5883e0cbfcd9b4c",
            "1a50eb50a3aab367cdd093972df61f6a7137b236e8bd63dd01440f61c12cdba1",
            "a7594596059725c45e9c2707cfafc7e9e71338e89c0248c1cec3fca59e6524f5",
            "72663aa17bf7314bc9d42b0bddbb5cc6c3aa33dbff82804f30ff149e140d355a"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/dark/job/variants/evidence/1"
        },
        {
          "id": "cards",
          "slide_count": 12,
          "native_objects": {
            "text": 37,
            "chart": 1,
            "process": 1,
            "table": 1
          },
          "png_sha256": [
            "a56c3cdc026582495b9b8ae69b54f0c0531f25dc551601ef639c1cff8add6dd2",
            "10e6df1ca6d2d6f30a73abf355538479f240654e01f292f841afdbe750513cf4",
            "87c183a53f58e02229ea3b5c0eb50c30cb3c296aaad026a11d3b64f60505cba7",
            "0b43187c7a9726ba4628d4f153c0500bc718524f40135ebdeb99009d3039d20f",
            "12581a01101254295a07f6ba8e4d4436045c886c9493b0738c9fb4ed59bf1676",
            "2724f9891463f18b992bc439dece29452373620f6990cda9b3bcd08af20a2fa1",
            "59a74f8d724b2c335601b20f7e8b65897afc4bca23e653e3cc7cd46eaf39ad33",
            "370d5dc57c120d49dae982dc54615f52ce1b201046f03237f6ff43ae6d0f9ccb",
            "4c2d0e86bad48f6456b729e850a1f5c33a858a5862ffcc08640a9b540f381954",
            "b2bf2026397aa04556ae32d46f8ffaac6995b6b474be925e235130cc3a3fa8b3",
            "49dbcebb4fae3d75017e360879f92225a35c1e085f6b9fa439b98a9b58e0cc98",
            "11c4d0aba74f36bcadb96b202274088c24af9719e6eb7c6ed8ab68b5a5dfeb1c"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/dark/job/variants/cards/1"
        }
      ],
      "claim_scope": "synthetic extractive pipeline; no live model or official template evaluation"
    },
    {
      "case": "grouped_protected",
      "status": "passed",
      "slide_count": 12,
      "pipeline_seconds": 7.333,
      "template_sha256": "44c9fa09f54420d3d51c1233cf4e63c6f406fa436952f140eaff69499f315426",
      "distinct_variants_per_slide": [
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true
      ],
      "variants": [
        {
          "id": "story",
          "slide_count": 12,
          "native_objects": {
            "text": 24,
            "chart": 1,
            "process": 1,
            "table": 1
          },
          "png_sha256": [
            "ce183a740d09e5ece2223cdbae1ba4b527497a00eb1ceae9defa963289fe4003",
            "b8363cab337e74f32f6327fde7a1019c15335559fc23b4f31520e20de09f624b",
            "1859f604d6a91b43c8ba5bf9ab16fd21f3a39b0e326c5af22659548f13145c1f",
            "6ed4253c16a5c7c1f403c6d7441ebb24093445657a5aa106f15e3427a3925fa6",
            "b1dc5ee8639f949f3d1a22474ce27d1bc9dd1e870b2cbc1839358541e1415c50",
            "00b37ff9a80495788385b113fe26c359cbed29572bee50ddceee07ccf84ad66d",
            "c5dfc681c79e6c35b21d52bca2f339457a9db1ecaf9776fc73f551ca5ebfbc07",
            "19ab1b3d7b43dbec2659cb5ab6d4f780e98fbe27da4b68a20b53c8c661d6a1a6",
            "74371db171b6cf82972be4d69673304c03fab59ab68ffd26296c3fbacb55d121",
            "9ba83b34bfb976e9c1c3967c20ee8c423bc627994e7c2adab9782af28fb4e8f6",
            "30c9ce1ff427941c8bd2a6cdf718a1b7c844ea7d693e45f80c1e73ced62921a9",
            "f3ecb3ce15ddc38c8683cdfa791eca0bc7875146ae0085ee6bdf72178be74d27"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/grouped_protected/job/variants/story/1"
        },
        {
          "id": "evidence",
          "slide_count": 12,
          "native_objects": {
            "text": 37,
            "table": 2,
            "process": 1
          },
          "png_sha256": [
            "4c74b3570d9f3213ce55a309bbb5bb3cd8467a1a42e0ca204376978e9bdd6ea4",
            "094cf256601cc74c6386e595ca3a80d8fe759a1411c7cf23e937f4d7d4ca9874",
            "1ba317efe3cd9d7627e0ec64ecf399e592d9dd4cac6153974329d7c243e9dab6",
            "740c0fb8f7583f264432b692b595dc0b133b697c183f128ba402580c29451a5b",
            "eb5251f2c70592c2eac9eac0ea7dc0d1402f127301ae9b5a32d6ad83cd333019",
            "213e7cb20b76dcd9bdf374f1e67a9f33b75aa82d52d41ca7d53daee5e470d32a",
            "43da95b7e5d49586182243784584cfabd4f18e422953cc0f836a85856684b493",
            "7782c7e3d43ca23d7a2978c3ae5c4cbb546589242b67c10bc1b475204b0e5831",
            "9db434593219f3e2cb5063c6f2f3052347bc0a3faec0e8e164f722b812818f4e",
            "18fd00ddd73224abd5757fbfb5c0a186ee670b741e16eec9579ff37c18e2cc01",
            "78fd382d0dd2f62c55693e9984b0bc8c05dda996cd29036ee0cdba03a2e50f69",
            "36178726c46096764f13533d4b7b68b87125095fb51fc436cdbf8867107cf190"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/grouped_protected/job/variants/evidence/1"
        },
        {
          "id": "cards",
          "slide_count": 12,
          "native_objects": {
            "text": 37,
            "chart": 1,
            "process": 1,
            "table": 1
          },
          "png_sha256": [
            "30f234f9a37c7680bd1042c11bc4a6155c68a381b866b83f3993697105ba0d00",
            "d896bb1613d5d2a829af94213ca4c1b7d2188cfe3ed18418072d9d310b820130",
            "8ed894e5509bdc4edf5d8c7b2c5bc32a6e44868ecdffb7eeb0dd9c3a166be15f",
            "0e728c7cf1df0a4153576496050f8d41158a728e8311db72f7db30cf0505d413",
            "d686d4eb5b6cabef67fba9d9b10d41306c38cd69750dc9f32ffb0d45ab80d19d",
            "4620f19fcdde25bcf49b3e731d8321f7ddf390475c91eaed40da4c556fc12205",
            "928a38178054144b4c23bfb21e9da7ae10a8c6f2b0a8d64b6faa6ec66963ce15",
            "95ed8f15fcc6d6117bc5e183cf4a3025aede8e347fff2023ce4acb7a109ffc13",
            "16570783786041808deaa7cdd59ece9d1b5c1dbf37cb685d70f26bcb29945a6c",
            "21d3a84a0da0eaf2dbcaa04bcf6942b5a33cbedba1f63ba6cb13496b06a020f0",
            "b665b9a75174d7afb22ffc4d1778869f65c774c1aa2fa02c81a08f28ce31b6fc",
            "782d226774e11ad5ef045ec5682890bdee8c2af165be50b5104bd68982cc6b30"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/grouped_protected/job/variants/cards/1"
        }
      ],
      "claim_scope": "synthetic extractive pipeline; no live model or official template evaluation"
    },
    {
      "case": "synthetic_holdout",
      "status": "passed",
      "slide_count": 10,
      "pipeline_seconds": 7.327,
      "template_sha256": "873c2310efed91fb6db18839d24f37ecab9f4583beea866b53d5992c977a1e7c",
      "distinct_variants_per_slide": [
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true,
        true
      ],
      "variants": [
        {
          "id": "story",
          "slide_count": 10,
          "native_objects": {
            "text": 20,
            "chart": 1,
            "process": 1,
            "table": 1
          },
          "png_sha256": [
            "7af843a1204f71ebb482a1f4250aefe8ebe47090c945df4763b64fe64a17e63b",
            "a2109cd82e992efb613951e5c1b5137755cd7b67ef2eccf32af94b213c067c9e",
            "2020b31382d92864fb8e6d7f24e7e97be9192d5497b61df228251ce877fa6c59",
            "bf92b0c85134fd0c1138b591fecc1cb4579628e051841d331d3e113ec7a5d329",
            "e5b90ff29a3e1c99d135373addb0549cddab1d568077e2f09234063cdc52d3e4",
            "7b0a82067834cd3094697e72a2757d39fc4327600b491268d593fa3e2daa1010",
            "2fa3b43e32bb3fcf7a437c1a308297fd035d43f8435be038575d153998399e79",
            "65eb7d623ea038ce7404d38e7ac37cb3397189b2c7dc5c11f499b8597e191714",
            "42fc4e7e7f68dd826a926beb427451b7b346879af5fabdfdcf7414437d419b43",
            "5a3a299d20574f15d8202b73604a938c8fdd425ad2978ae55ae1446c0f741aa4"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/synthetic_holdout/job/variants/story/1"
        },
        {
          "id": "evidence",
          "slide_count": 10,
          "native_objects": {
            "text": 31,
            "table": 2,
            "process": 1
          },
          "png_sha256": [
            "02713469aa92c4522f668104f8fa8c251ce42dc0b6b5d1a5b2e391379fb738ae",
            "3af485c905c075c92c81776d6a8b584276b3f3f6774def9125bbca7593ba1bdd",
            "61e29f07a61c2501d4e476b89ecfbcd30a27fcbc5280b1ebecfeaca0e860c2e8",
            "78b353d8a81b7d2d5432b27bab9b098dab518c98b8b9553339250dead72e4dde",
            "41e29a5a0c594540ff912ec2f30f370a545657b6e8578d8af77e89e7d883bd68",
            "2e7b8cc8f3386245a98c92216a9cea8c6b1bd43b300af1e73b88860937f5c705",
            "2b44d0c693eef9926828b46e659bd6cbd9b45a34158f43578d2711f74eff4a62",
            "83934ea4e6359a0f92e5d97450e8909111fe9e994dfcbb920737602caf49859a",
            "edba47cc4b6a8d2951a1c57f40c7c68ff1651fe5538c4cbd6084955a34c1a702",
            "5a2f70cf3fc78478e5028d02abd0ea359648aafa73209fcf4d3c477668deb60a"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/synthetic_holdout/job/variants/evidence/1"
        },
        {
          "id": "cards",
          "slide_count": 10,
          "native_objects": {
            "text": 31,
            "chart": 1,
            "process": 1,
            "table": 1
          },
          "png_sha256": [
            "e4a649ba217eeb877c08b5e6d39986c71abcb03da7990ea4e397d5e5f73b2beb",
            "00c1c2753e9617854f4ff8b66c06647b640d628db98910caab76e6d02e517306",
            "876940ba1cb3ba2456798976ced0cb2544d525105b30483c31c886b8f3203117",
            "bbd7db7ce8c2528c8ffe98d5d83e45bb227181887419185cf4b44949cdbca01f",
            "52d9f136faa778cec7bba44be6c5c82b8e58916c61d3f9cc44e129aa14d7c6c0",
            "df838478624abbe3c9c1c4aae8e6b455233912be7f14ff2fc30f0574fcb3ed3e",
            "2bb2bc639c76226525a9205b604571f91a41b9b950fa728c84e994d978177ba0",
            "33b4e531779114241952facc46e597ec1fe4aa79c53eedfc8871f08032c0e243",
            "8204401a56d37a894d893e17b1ce7d3e55edcfae4d3dfd7296cbd1c3c0c52628",
            "bf4fb731369b6381107c9ed993908c0fed3961c0ca33de66718de547fcc2436d"
          ],
          "audit": {
            "errors": 0,
            "warnings": 0,
            "rules": {},
            "contextual_status": "not_run"
          },
          "html_visual": "png",
          "artifact_directory": "/private/tmp/exposlides-designer-benchmark-20260927-accepted-final/synthetic_holdout/job/variants/cards/1"
        }
      ],
      "claim_scope": "synthetic extractive pipeline; no live model or official template evaluation"
    }
  ],
  "limitations": [
    "Все шаблоны и данные синтетические; это не шаблоны организатора.",
    "Нет оценки живой Qwen, VK endpoint, VLM или генератора изображений.",
    "Разные PNG подтверждают различие рендеров, но не дизайнерское качество.",
    "Audit warnings/errors сохраняются для разбора; passed означает структурные проверки."
  ]
}
```

</details>

<details>
<summary>Manifest четырёх случаев</summary>

```json
{
  "dark": {
    "schema_version": "1.0",
    "template_sha256": "8992cbc81b5a911d97e939acccdb7b036c2a0ce187c9d9be22150448ea5860c5",
    "source_sha256": "de8c2fb80ac33ac3c736e3c3c1d538777edffdaf88985736edf1dfcfe02027d6",
    "request_sha256": "60a8a8e6ee0b4a76b2e6e0f97cd10dc5031db293f04ed3a954d43ae5e28b93a0",
    "story_model": null,
    "mode": "extractive",
    "versioned_resources": {
      "prompts/designer/audit.md": "dc7fa5014a07394b813d50ae27177d619c026d5b448831a2d75e2a71d106712f",
      "prompts/designer/image.md": "662920a65aba6bb8734a571c886a071ba44077139aeb90acd1dd5c6d72da2177",
      "prompts/designer/story.md": "7e378021c104fb36e08c86d61d741201fd453af8b803d45416ede172bf3d2c70",
      "config/models.toml": "356739ee8a279cf86ca3e25950ef8f45cae56f83b1fda27d5d6b282ae01bbe42",
      "config/run.example.toml": "8961e96eb23d1f467eae68ccf4a66531a03a916dde5b322951f3a1af84cb20aa",
      "config/skills.toml": "a944a4d42ee7dd177ba3c30e020f973986f240cde22e6c3f8ea8863646fa2991",
      "agents/designer.toml": "7677d07dcc05e8b939df83f13630e4c9cff709248803abdf00540612daf455ab"
    },
    "contextual_audit_requested": false,
    "workflow": {
      "id": "designer",
      "version": "1.0.0"
    },
    "model_registry_version": "1.0.0",
    "declared_models": {
      "qwen_3_8_27b": {
        "id": "Qwen/Qwen3.8-27B",
        "license": "Apache-2.0",
        "parameters_billions": 27,
        "live_endpoint_verified": false
      },
      "flux_1_schnell": {
        "id": "black-forest-labs/FLUX.1-schnell",
        "license": "Apache-2.0",
        "parameters_billions": 12,
        "live_endpoint_verified": false
      }
    },
    "limits": {
      "seconds": 300,
      "slides": 12
    }
  },
  "grouped_protected": {
    "schema_version": "1.0",
    "template_sha256": "44c9fa09f54420d3d51c1233cf4e63c6f406fa436952f140eaff69499f315426",
    "source_sha256": "de8c2fb80ac33ac3c736e3c3c1d538777edffdaf88985736edf1dfcfe02027d6",
    "request_sha256": "60a8a8e6ee0b4a76b2e6e0f97cd10dc5031db293f04ed3a954d43ae5e28b93a0",
    "story_model": null,
    "mode": "extractive",
    "versioned_resources": {
      "prompts/designer/audit.md": "dc7fa5014a07394b813d50ae27177d619c026d5b448831a2d75e2a71d106712f",
      "prompts/designer/image.md": "662920a65aba6bb8734a571c886a071ba44077139aeb90acd1dd5c6d72da2177",
      "prompts/designer/story.md": "7e378021c104fb36e08c86d61d741201fd453af8b803d45416ede172bf3d2c70",
      "config/models.toml": "356739ee8a279cf86ca3e25950ef8f45cae56f83b1fda27d5d6b282ae01bbe42",
      "config/run.example.toml": "8961e96eb23d1f467eae68ccf4a66531a03a916dde5b322951f3a1af84cb20aa",
      "config/skills.toml": "a944a4d42ee7dd177ba3c30e020f973986f240cde22e6c3f8ea8863646fa2991",
      "agents/designer.toml": "7677d07dcc05e8b939df83f13630e4c9cff709248803abdf00540612daf455ab"
    },
    "contextual_audit_requested": false,
    "workflow": {
      "id": "designer",
      "version": "1.0.0"
    },
    "model_registry_version": "1.0.0",
    "declared_models": {
      "qwen_3_8_27b": {
        "id": "Qwen/Qwen3.8-27B",
        "license": "Apache-2.0",
        "parameters_billions": 27,
        "live_endpoint_verified": false
      },
      "flux_1_schnell": {
        "id": "black-forest-labs/FLUX.1-schnell",
        "license": "Apache-2.0",
        "parameters_billions": 12,
        "live_endpoint_verified": false
      }
    },
    "limits": {
      "seconds": 300,
      "slides": 12
    }
  },
  "ordinary_textboxes": {
    "schema_version": "1.0",
    "template_sha256": "1453b7b66b88259fcf0e5996d7c6a5bd0e3b6034ce7493c9b694dcbf2433c229",
    "source_sha256": "de8c2fb80ac33ac3c736e3c3c1d538777edffdaf88985736edf1dfcfe02027d6",
    "request_sha256": "60a8a8e6ee0b4a76b2e6e0f97cd10dc5031db293f04ed3a954d43ae5e28b93a0",
    "story_model": null,
    "mode": "extractive",
    "versioned_resources": {
      "prompts/designer/audit.md": "dc7fa5014a07394b813d50ae27177d619c026d5b448831a2d75e2a71d106712f",
      "prompts/designer/image.md": "662920a65aba6bb8734a571c886a071ba44077139aeb90acd1dd5c6d72da2177",
      "prompts/designer/story.md": "7e378021c104fb36e08c86d61d741201fd453af8b803d45416ede172bf3d2c70",
      "config/models.toml": "356739ee8a279cf86ca3e25950ef8f45cae56f83b1fda27d5d6b282ae01bbe42",
      "config/run.example.toml": "8961e96eb23d1f467eae68ccf4a66531a03a916dde5b322951f3a1af84cb20aa",
      "config/skills.toml": "a944a4d42ee7dd177ba3c30e020f973986f240cde22e6c3f8ea8863646fa2991",
      "agents/designer.toml": "7677d07dcc05e8b939df83f13630e4c9cff709248803abdf00540612daf455ab"
    },
    "contextual_audit_requested": false,
    "workflow": {
      "id": "designer",
      "version": "1.0.0"
    },
    "model_registry_version": "1.0.0",
    "declared_models": {
      "qwen_3_8_27b": {
        "id": "Qwen/Qwen3.8-27B",
        "license": "Apache-2.0",
        "parameters_billions": 27,
        "live_endpoint_verified": false
      },
      "flux_1_schnell": {
        "id": "black-forest-labs/FLUX.1-schnell",
        "license": "Apache-2.0",
        "parameters_billions": 12,
        "live_endpoint_verified": false
      }
    },
    "limits": {
      "seconds": 300,
      "slides": 12
    }
  },
  "synthetic_holdout": {
    "schema_version": "1.0",
    "template_sha256": "873c2310efed91fb6db18839d24f37ecab9f4583beea866b53d5992c977a1e7c",
    "source_sha256": "41aebd19e868a8b3a98219e3076a3e27b48dc7c033ee8ae79567a34562d93d13",
    "request_sha256": "4d99728e2e759f66935ebfe48e659eac8dc5f697555108268bcdde901d6ee5c6",
    "story_model": null,
    "mode": "extractive",
    "versioned_resources": {
      "prompts/designer/audit.md": "dc7fa5014a07394b813d50ae27177d619c026d5b448831a2d75e2a71d106712f",
      "prompts/designer/image.md": "662920a65aba6bb8734a571c886a071ba44077139aeb90acd1dd5c6d72da2177",
      "prompts/designer/story.md": "7e378021c104fb36e08c86d61d741201fd453af8b803d45416ede172bf3d2c70",
      "config/models.toml": "356739ee8a279cf86ca3e25950ef8f45cae56f83b1fda27d5d6b282ae01bbe42",
      "config/run.example.toml": "8961e96eb23d1f467eae68ccf4a66531a03a916dde5b322951f3a1af84cb20aa",
      "config/skills.toml": "a944a4d42ee7dd177ba3c30e020f973986f240cde22e6c3f8ea8863646fa2991",
      "agents/designer.toml": "7677d07dcc05e8b939df83f13630e4c9cff709248803abdf00540612daf455ab"
    },
    "contextual_audit_requested": false,
    "workflow": {
      "id": "designer",
      "version": "1.0.0"
    },
    "model_registry_version": "1.0.0",
    "declared_models": {
      "qwen_3_8_27b": {
        "id": "Qwen/Qwen3.8-27B",
        "license": "Apache-2.0",
        "parameters_billions": 27,
        "live_endpoint_verified": false
      },
      "flux_1_schnell": {
        "id": "black-forest-labs/FLUX.1-schnell",
        "license": "Apache-2.0",
        "parameters_billions": 12,
        "live_endpoint_verified": false
      }
    },
    "limits": {
      "seconds": 300,
      "slides": 10
    }
  }
}
```

</details>
