FROM ghcr.io/converged-computing/rainbow-scheduler:latest

# docker build -t vanessa/rainbow-scheduler:latest .
# gcloud run deploy rainbow-service --region us-central1 --image docker.io/vanessa/rainbow-scheduler:latest --max-instances 1
# Note the above didn't work great, still testing with kind

COPY ./entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD []
