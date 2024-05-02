## Cloned from Koyeb-Django for quickstart.  For hosting climate-related data visualizations, for the Terra.do class project mainly but also freelance visualizations.

To run this repo locally:

1. If you haven't already, set up Git on your machine
   1a. make sure you have a local SSH keypair and that the public key of the keypair is installed on your Github account for authorization.

2. If you haven't already, install python3 and virtualenvwrapper on your machine.

3. On your command line, `cd` to the directory you want and run:

`git clone git@github.com:jonoxia/climate-data-viz-django.git`

4. `cd` into the new directory. Run:

`mkvirtualenv climate-data-viz-django`

  4a. next time you restart your computer or terminal window, use `workon climate-data-viz-django` to reconnect to this virtual environment.

5. Install the python prerequisites. Run:

`pip3 install -r requirements.txt`

6. Ask the project maintainer for the API keys, which for security reasons are not part of this repo. Export them on your command line, like so:

`export GOOGLE_MAPS_API_KEY='xxxxxxxxxx'`

7. Start the django server:

`python manage.py runserver`

8. Go to `127.0.0.1:8000` in your web browser to view the site.