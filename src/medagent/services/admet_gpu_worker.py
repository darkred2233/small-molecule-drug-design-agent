"""Run ADMET-AI in the dedicated CUDA environment."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    from admet_ai import ADMETModel

    if len(sys.argv) == 2 and sys.argv[1] == "--probe":
        import torch

        print(json.dumps({"available": bool(torch.cuda.is_available())}))
        return 0
    if len(sys.argv) != 3:
        raise SystemExit("usage: admet_gpu_worker.py INPUT_JSON OUTPUT_JSON")

    input_path, output_path = (Path(value) for value in sys.argv[1:])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    model = ADMETModel(num_workers=0)
    predictions = model.predict(smiles=payload["smiles"])
    output_path.write_text(
        json.dumps(
            {
                "device": str(model.device),
                "index": [str(value) for value in predictions.index],
                "records": predictions.to_dict(orient="records"),
            }
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
