from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class DataQualityMetrics:
    total_records: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    additional_stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def schema_compliance_ratio(self) -> float:
        if self.total_records == 0:
            return 1.0
        return round(self.valid_records / self.total_records, 4)

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "schema_compliance_ratio": self.schema_compliance_ratio,
        }
        res.update(self.additional_stats)
        return res
