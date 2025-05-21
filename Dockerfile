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

# Create plugin directory
RUN mkdir -p /opt/openmct/plugins/fruiting-chamber

# Copy our plugin files
COPY plugins/fruiting-chamber/plugin.js /opt/openmct/plugins/fruiting-chamber/
COPY plugins/fruiting-chamber/plugin.css /opt/openmct/plugins/fruiting-chamber/
COPY plugins/fruiting-chamber/index.js /opt/openmct/plugins/fruiting-chamber/

WORKDIR /opt/openmct
EXPOSE 8080
ENTRYPOINT ["npm", "start", "--", "--host", "0.0.0.0"] 