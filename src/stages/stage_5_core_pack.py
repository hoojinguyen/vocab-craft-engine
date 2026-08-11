"""Stage 5: Core Pack — Select 3000 core words, quality gates, audio, export."""

import logging
from config.settings import NGSL_PATH, OUTPUT_DIR
from src.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


def stage_5_core_pack(ctx: PipelineContext):
    """Build curated Core 3000 word pack from exported SQLite DB."""
    from src.export.core_pack_builder import CorePackBuilder
    from src.nlp.cefr_grader import CEFRGrader
    from config.settings import SUBTLEX_FREQ_PATH

    grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
    freq_dict = dict(grader.freq_dict)

    pack_dir = OUTPUT_DIR / "core_pack"
    builder = CorePackBuilder(source_db_path=ctx.sqlite_path, output_dir=pack_dir)

    report = builder.build(
        freq_dict=freq_dict,
        ngsl_path=NGSL_PATH,
        vi_budget=ctx.vi_budget,
    )

    logger.info(
        "[Stage 5] Core pack built: %s words, pass_rate %.1f%%, %s quarantined, %s themes",
        report["selected"], report["pass_rate"] * 100,
        report["quarantined"], report["themes_covered"],
    )
    ctx.stats["core_pack"] = report
