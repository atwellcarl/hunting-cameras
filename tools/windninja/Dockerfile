# WindNinja (US Forest Service fire lab) for modeling wind over the properties' terrain.
# Built from the official source at a fixed release, command line only: the standard mass-conserving solver
# with the diurnal (thermal slope flow) model. No GUI, no OpenFOAM momentum solver, and no "phone home" usage
# queries. (Weather-model and LCP support are compiled in because the solver links against them; our runs
# don't use them.)
#
#   docker build -t buckbook-windninja tools/windninja
#   docker run --rm -v "$PWD/data/wind:/data" buckbook-windninja WindNinja_cli /data/run.cfg
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates pkg-config \
      libgdal-dev gdal-bin libshp-dev libnetcdf-dev libcurl4-gnutls-dev \
      libboost-date-time-dev libboost-program-options-dev libboost-test-dev \
    && rm -rf /var/lib/apt/lists/*
ARG WINDNINJA_TAG=4.0.0
RUN git clone --depth 1 --branch ${WINDNINJA_TAG} https://github.com/firelab/windninja.git /opt/src/windninja
WORKDIR /opt/src/windninja/build
RUN cmake .. \
      -D NINJA_GUI=OFF -D NINJA_CLI=ON -D NINJAFOAM=OFF \
      -D DISABLE_THREDDS_UPDATE=ON -D ENABLE_GMTED=OFF \
      -D PHONE_HOME_QUERIES=OFF -D SUPRESS_WARNINGS=ON \
    && make -j"$(nproc)" WindNinja_cli \
    && install -m 755 src/cli/WindNinja_cli /usr/local/bin/
ENV WINDNINJA_DATA=/opt/src/windninja/data
WORKDIR /data
