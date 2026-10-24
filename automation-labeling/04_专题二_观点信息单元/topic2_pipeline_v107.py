"""Current topic-two entry. v106 callers also use the corrected local scorer."""
from topic2_pipeline_v106 import configure,create_runner,process_document,process_saved,score_completed,prepare_export,aggregate,export_workbook
from slice_sentiment_v107 import LocalScorer
