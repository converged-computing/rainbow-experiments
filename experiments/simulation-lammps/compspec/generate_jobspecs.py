#!/usr/bin/env python3

import argparse
import json
import os
import rainbow.jobspec.converter as converter
import yaml
import re

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)


def recursive_find(base, pattern="^(compspec[.]json)$"):
    """
    Recursively find lammps output files.
    """
    for root, _, filenames in os.walk(base):
        for filename in filenames:
            if re.search(pattern, filename):
                yield os.path.join(root, filename)


def read_json(filename):
    """
    Read json from file
    """
    return json.loads(read_file(filename))


def read_file(filename):
    """
    Read content from file
    """
    with open(filename, "r") as fd:
        content = fd.read()
    return content


def load_yaml(filename):
    """
    Read yaml from file.
    """
    with open(filename, "r") as stream:
        content = yaml.safe_load(stream)
    return content


def write_yaml(data, filename):
    """
    Write yaml to file
    """
    with open(filename, "w") as outfile:
        yaml.dump(data, outfile)


def get_parser():
    parser = argparse.ArgumentParser(description="compspec to jobspec generator")
    parser.add_argument(
        "--indir",
        default=here,
        help="Input directory with *compspec.json",
    )
    parser.add_argument(
        "--outdir",
        default=os.path.join(root, "jobspecs"),
        help="output directory for jobspecs",
    )
    parser.add_argument(
        "--nodes",
        type=int,
        default=2,
        help="number of nodes the application will run on",
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=4,
        help="number of tasks (processes) the application will need",
    )
    return parser


def compspec_file_to_jobspec_file(filename):
    """
    Convert the compspec.json to a jobspec yaml name
    """
    basename = os.path.basename(filename)
    return basename.replace("-compspec.json", "-jobspec.yaml")


def main():
    parser = get_parser()
    args, _ = parser.parse_known_args()

    # Also organize results by mode
    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)

    # Show parameters to the user
    print(f"▶️  Output directory: {args.outdir}")
    print(f"▶️   Input directory: {args.indir}")

    # These are the levels (and associated groups we include for each)
    # A lookup of the attributes we care about for each level
    levels = {
        "platform": {"io.archspec": ["cpu.target"]},
        "os": {"io.archspec": ["cpu.target"], "os": ["os.name", "os.vendor"]},
        "os-version": {
            "io.archspec": ["cpu.target"],
            "os": ["os.name", "os.vendor", "os.release"],
        },
        "descriptive": {
            "io.archspec": ["cpu.target"],
            "hardware": ["hardware.gpu.available"],
            "os": ["os.name", "os.release", "os.vendor"],
        },
        "mpi": {
            "io.archspec": ["cpu.target"],
            "hardware": ["hardware.gpu.available"],
            "os": ["os.name", "os.release", "os.vendor"],
            "mpi": ["mpi.implementation", "mpi.version"],
        },
    }
    inputs = recursive_find(args.indir, ".+compspec[.]json")
    for input_file in inputs:
        # We need to generate a jobspec for each compatibility level.
        compspec = read_json(input_file)
        command = [
            "lmp",
            "-v",
            "x",
            "2",
            "-v",
            "y",
            "2",
            "-v",
            "z",
            "2",
            "-in",
            "./in.reaxff.hns",
            "-nocite",
        ]
        if "gpu" in input_file:
            command[0] = "lmp_gpu"

        # Generate a jobspec for each level
        for level, attributes in levels.items():
            js = converter.from_compatibility_spec(
                compspec,
                command,
                args.nodes,
                tasks=args.tasks,
                name=f"lammps-{level}",
                attributes=attributes,
            )
            outdir = os.path.join(args.outdir, level)
            if not os.path.exists(outdir):
                os.makedirs(outdir)
            outfile = compspec_file_to_jobspec_file(input_file)
            outfile = os.path.join(outdir, outfile)
            print(f"Writing {level} jobspec {os.path.basename(outfile)}")
            write_yaml(js, outfile)


if __name__ == "__main__":
    main()
