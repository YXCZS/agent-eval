"""Generate the checked-in OpenAPI snapshot used by frontend contract checks."""

import json
from pathlib import Path

from agent_eval_api.main import app

output = Path(__file__).resolve().parents[1] / "packages" / "contracts" / "openapi.json"
output.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(output)
