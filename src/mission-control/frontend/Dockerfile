FROM ros:jazzy-ros-core


ENV NPM_CONFIG_LOGLEVEL=info

WORKDIR /opt

RUN apt-get update && apt-get install -y \
    git \
    npm \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/nasa/openmct.git && \
    cd openmct && \
    npm install

WORKDIR /opt/openmct
EXPOSE 8080
ENTRYPOINT ["npm", "start", "--", "--host", "0.0.0.0"]