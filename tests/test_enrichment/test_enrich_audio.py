from src.pipeline.steps.enrich_audio import EnrichAudioStep


def test_enrich_audio_step_optional_flag():
    step = EnrichAudioStep()
    assert step.name == "enrich_audio"
    assert step.optional is True
    assert step.execution_type == "io"
