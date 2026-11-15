# Forge worker image.
#
# Two stages. The `core` stage carries only the deterministic kernel and its one
# dependency, which is all the trust core needs and is what runs in the isolated
# worker. The `solvers` stage adds the heavy CAD and simulation stack.
#
# Keeping them separate is a security decision, not a size optimisation: the
# stage that executes geometry code derived from model output should contain as
# little as possible.

# The base: Python 3.12 on Debian by default; any image with Python 3.10 or later
# (docs/V2-stage3.md, 2.6; scripts/docker_base_from_archive.sh makes one from
# Ubuntu 24.04's archive where no registry can be reached):
#   docker build --build-arg BASE=<image> .
ARG BASE=python:3.12-slim
FROM ${BASE} AS core

RUN useradd --create-home --shell /usr/sbin/nologin forge
WORKDIR /app

RUN pip install --no-cache-dir numpy==2.1.3

COPY packages/ /app/packages/
COPY examples/ /app/examples/
COPY schemas/ /app/schemas/
COPY tests/ /app/tests/
COPY Makefile pyproject.toml /app/
# Readable by the worker whatever modes the checkout gave the files.
RUN chmod -R a+rX /app

ENV PYTHONPATH=/app/packages
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

USER forge
ENTRYPOINT ["python3", "-m", "forge_cli"]
CMD ["--help"]


# ----------------------------------------------------------------------
FROM core AS solvers

USER root
# OpenCascade, Gmsh and CalculiX. Gmsh and CalculiX are GPL and are invoked as
# separate processes over files, never linked -- see LICENSE-DECISION.md.
RUN apt-get update && apt-get install --no-install-recommends -y \
      libgl1 libglu1-mesa libxrender1 libxext6 calculix-ccx \
 && rm -rf /var/lib/apt/lists/*
# The exact kernel's pins (pyproject's `exact` extra): forge_occ runs on this
# OpenCascade only, and refuses any other.
RUN pip install --no-cache-dir cadquery-ocp-novtk==7.9.3.1.1 lib3mf==2.5.0 gmsh==4.13.1
USER forge
