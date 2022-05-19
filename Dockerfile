# Dockerfile for base image towards satisfying gisobuild
# dependencies.
#
FROM almalinux:8
COPY setup/prep_dependency.sh /tmp
WORKDIR /app/gisobuild
RUN /tmp/prep_dependency.sh && rm /tmp/prep_dependency.sh
