import logging
from typing import Tuple
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.context import PipelineContext
from src.pipeline.core.result import StepResult, StepStatus
from config.settings import EXPORT_SQLITE_PATH, OUTPUT_DIR, NGSL_PATH, SUBTLEX_FREQ_PATH
from src.nlp.cefr_grader import CEFRGrader
from src.export.core_pack_builder import CorePackBuilder

logger = logging.getLogger(__name__)


class CorePackStep(BaseStep):
    name = "core_pack"
    description = "Curate and export Core 3000 Pack (core_3000.db)"

    def should_skip(self, context: PipelineContext) -> Tuple[bool, str]:
        if not getattr(context.args, "build_core_pack", False):
            return True, "Flag --build-core-pack NOT set."
        return False, ""

    def run(self, context: PipelineContext) -> StepResult:
        logger.info("[Step 13] Building Core 3000 Word Pack...")
        grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
        freq_dict = dict(grader.freq_dict)
        if not freq_dict:
            raise RuntimeError("SUBTLEX frequency dictionary is empty or unavailable")

        pack_dir = OUTPUT_DIR / "core_pack"
        source_db = context.db_manager.db_path if (context and getattr(context, "db_manager", None) and hasattr(context.db_manager, "db_path")) else EXPORT_SQLITE_PATH
        builder = CorePackBuilder(source_db_path=source_db, output_dir=pack_dir)
        if getattr(context.args, "force_reset", False):
            builder.reset()
        vi_budget = getattr(context.args, "vi_budget", 1000)
        report = builder.build(freq_dict=freq_dict, ngsl_path=NGSL_PATH, vi_budget=vi_budget)

        logger.info(
            "[Step 13] Core pack built: %s words, pass rate %.1f%%.",
            f"{report['selected']:,}",
            report["pass_rate"] * 100,
        )
        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=report["selected"],
            metrics=report,
        )
