#!/bin/bash

sudo git pull
sudo chown -R www-data: .
sudo systemctl restart gunicorn