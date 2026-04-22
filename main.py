from __future__ import annotations

import sys

from soc_pipeline.application.pipeline import run_once, run_poll
from soc_pipeline.application.training import run_training
from soc_pipeline.infrastructure.config import build_parser, load_runtime_config


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = load_runtime_config(args)
        if args.command == "poll":
            return run_poll(config=config, force=args.force)
        if args.command == "train":
            return run_training(config=config)
        return run_once(config=config, force=args.force)
    except KeyboardInterrupt:
        print("Execution interrupted.")
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
