# =================================================================
#
# Authors: Tom Kralidis <tomkralidis@gmail.com>,
# Just van den Broecke <justb4@gmail.com>
#
# Copyright (c) 2014 Tom Kralidis
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# =================================================================

from datetime import datetime
import logging
import json

from sqlalchemy import func

from enums import RESOURCE_TYPES
from init import DB
from notifications import notify
from factory import Factory
import util

LOGGER = logging.getLogger(__name__)


class Run(DB.Model):
    """measurement of resource state"""

    identifier = DB.Column(DB.Integer, primary_key=True, autoincrement=True)
    resource_identifier = DB.Column(DB.Integer,
                                    DB.ForeignKey('resource.identifier'))
    resource = DB.relationship('Resource',
                               backref=DB.backref('runs', lazy='dynamic'))
    checked_datetime = DB.Column(DB.DateTime, nullable=False)
    success = DB.Column(DB.Boolean, nullable=False)
    response_time = DB.Column(DB.Float, nullable=False)
    message = DB.Column(DB.Text, default='OK')

    def __init__(self, resource, success, response_time, message='OK',
                 checked_datetime=datetime.utcnow()):
        self.resource = resource
        self.success = success
        self.response_time = response_time
        self.checked_datetime = checked_datetime
        self.message = message

    def __repr__(self):
        return '<Run %r>' % (self.identifier)


class Probe(DB.Model):
    """Identifies and parameterizes ProbeRunner, applies to single Resource"""

    identifier = DB.Column(DB.Integer, primary_key=True, autoincrement=True)
    resource_identifier = DB.Column(DB.Integer,
                                    DB.ForeignKey('resource.identifier'))
    resource = DB.relationship('Resource',
                               backref=DB.backref('probes', lazy='dynamic'))
    proberunner = DB.Column(DB.Text, nullable=False)

    # JSON string object specifying actual parameters for the Probe
    # See http://docs.sqlalchemy.org/en/latest/orm/mapped_attributes.html
    _parameters = DB.Column("parameters", DB.Text, default='{}')

    def __init__(self, resource, proberunner, parameters='{}'):
        self.resource = resource
        self.proberunner = proberunner
        self.parameters = parameters

    @property
    def parameters(self):
        return json.loads(self._parameters)
        # First get parameters already valued from ProbeRunner

        # TODO not here but in GUI (adding values and defaults)
        # parms = {}
        # runner_parms = self.proberunner_parameters
        # for parm in runner_parms:
        #     parms[parm['name']] = None
        #     if 'value' in parm:
        #         parms[parm['name']] = parm['value']
        #
        # for key in parms:
        #     if key in probe_parms:
        #         parms[key] = probe_parms[key]
        #
        # return parms

    @parameters.setter
    def parameters(self, parameters):
        self._parameters = json.dumps(parameters)

    @property
    def proberunner_instance(self):
        return Factory.create_obj(self.proberunner)

    @property
    def name(self):
        return self.proberunner_instance.NAME

    @property
    def proberunner_parameters(self):
        return self.proberunner_instance.REQUEST_PARAMETERS

    def __repr__(self):
        return '<Probe %r>' % self.identifier


class Check(DB.Model):
    """Identifies and parameterizes check function, applies to single Probe"""

    identifier = DB.Column(DB.Integer, primary_key=True, autoincrement=True)
    probe_identifier = DB.Column(DB.Integer, DB.ForeignKey('probe.identifier'))
    probe = DB.relationship('Probe',
                               backref=DB.backref('checks', lazy='dynamic'))
    checker = DB.Column(DB.Text, nullable=False)

    # JSON string object specifying actual parameters for the Check
    # See http://docs.sqlalchemy.org/en/latest/orm/mapped_attributes.html
    _parameters = DB.Column("parameters", DB.Text, default='{}')

    def __init__(self, probe, checker, parameters='{}'):
        self.probe = probe
        self.checker = checker
        self.parameters = parameters

    @property
    def parameters(self):
        return json.loads(self._parameters)

    @parameters.setter
    def parameters(self, parameters):
        self._parameters = json.dumps(parameters)


    def __repr__(self):
        return '<Check %r>' % self.identifier


class Tag(DB.Model):
    id = DB.Column(DB.Integer, primary_key=True)
    name = DB.Column(DB.String(100), unique=True, nullable=False)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<Tag %r>' % (self.name)

resource_tags = DB.Table('resource_tags',
                         DB.Column('identifier', DB.Integer, primary_key=True,
                                   autoincrement=True),
                         DB.Column('tag_id', DB.Integer,
                                   DB.ForeignKey('tag.id')),
                         DB.Column('resource_identifier', DB.Integer,
                                   DB.ForeignKey('resource.identifier')))


class Resource(DB.Model):
    """HTTP accessible resource"""

    identifier = DB.Column(DB.Integer, primary_key=True, autoincrement=True)
    resource_type = DB.Column(DB.Text, nullable=False)
    title = DB.Column(DB.Text, nullable=False)
    url = DB.Column(DB.Text, nullable=False)
    latitude = DB.Column(DB.Float)
    longitude = DB.Column(DB.Float)
    owner_identifier = DB.Column(DB.Text, DB.ForeignKey('user.username'))
    owner = DB.relationship('User',
                            backref=DB.backref('username2', lazy='dynamic'))
    tags = DB.relationship('Tag', secondary=resource_tags, backref='resource')

    def __init__(self, owner, resource_type, title, url, tags):
        self.resource_type = resource_type
        self.title = title
        self.url = url
        self.owner = owner
        self.tags = tags

        # get latitude/longitude from hostname
        try:
            self.latitude, self.longitude = util.geocode(url)
        except Exception as err:  # skip storage
            LOGGER.exception('Could not derive coordinates: %s', err)

    def __repr__(self):
        return '<Resource %r %r>' % (self.identifier, self.title)

    @property
    def get_capabilities_url(self):
        if self.resource_type.startswith('OGC:'):
            url = '%s%s' % (self.url,
                            RESOURCE_TYPES[self.resource_type]['capabilities'])
        else:
            url = self.url
        return url

    @property
    def all_response_times(self):
        result = 0
        if self.runs.count() > 0:
            result = [run.response_time for run in self.runs]
        return result

    @property
    def first_run(self):
        return self.runs.order_by(
                Run.checked_datetime.asc()).first()

    @property
    def last_run(self):
        return self.runs.order_by(
                Run.checked_datetime.desc()).first()

    @property
    def average_response_time(self):
        result = 0
        if self.runs.count() > 0:
            query = [run.response_time for run in self.runs]
            result = util.average(query)
        return result

    @property
    def min_response_time(self):
        result = 0
        if self.runs.count() > 0:
            query = [run.response_time for run in self.runs]
            result = min(query)
        return result

    @property
    def max_response_time(self):
        result = 0
        if self.runs.count() > 0:
            query = [run.response_time for run in self.runs]
            result = max(query)
        return result

    @property
    def reliability(self):
        result = 0
        if self.runs.count() > 0:
            total_runs = self.runs.count()
            success_runs = self.runs.filter_by(success=True).count()
            result = util.percentage(success_runs, total_runs)
        return result

    @property
    def tags2csv(self):
        return ','.join([t.name for t in self.tags])

    def snippet(self):
        return util.get_python_snippet(self)

    def runs_to_json(self):
        runs = []
        for run in self.runs.order_by(Run.checked_datetime).all():
            runs.append({'datetime': run.checked_datetime.isoformat(),
                         'value': run.response_time,
                         'success': 1 if run.success else 0})
        return runs

    def success_to_colors(self):
        colors = []
        for run in self.runs.order_by(Run.checked_datetime).all():
            if run.success == 1:
                colors.append('#5CB85C')  # green
            else:
                colors.append('#D9534F')  # red
        return colors


class User(DB.Model):
    """user accounts"""

    identifier = DB.Column('user_id', DB.Integer, primary_key=True,
                           autoincrement=True)
    username = DB.Column(DB.String(20), unique=True, index=True,
                         nullable=False)
    password = DB.Column(DB.String(255), nullable=False)
    email = DB.Column(DB.String(50), unique=True, index=True, nullable=False)
    role = DB.Column(DB.Text, nullable=False, default='user')
    registered_on = DB.Column(DB.DateTime)

    def __init__(self, username, password, email, role='user'):
        self.username = username
        self.password = password
        self.email = email
        self.role = role
        self.registered_on = datetime.utcnow()

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return unicode(self.identifier)

    def __repr__(self):
        return '<User %r>' % (self.username)


def get_resource_types_counts():
    """return frequency counts and totals of registered resource types"""

    mrt = Resource.resource_type
    return [
        DB.session.query(mrt, func.count(mrt)).group_by(mrt),
        DB.session.query(mrt).count()
    ]


def get_tag_counts():
    """return counts of all tags"""

    query = DB.session.query(Tag.name,
                             DB.func.count(Resource.identifier)).join(
                             Resource.tags).group_by(Tag.id)
    return dict(query)


def load_data(file_path):
    # Beware!
    DB.drop_all()
    db_commit()

    # In particular for Postgres to drop connections
    DB.session.close()

    DB.create_all()

    with open(file_path) as ff:
        objects = json.load(ff)

    # add users, keeping track of DB objects
    users = {}
    for user_name in objects['users']:
        user = objects['users'][user_name]
        user = User(user['username'],
                    user['password'],
                    user['email'],
                    user['role'])
        users[user_name] = user
        DB.session.add(user)

    # add tags, keeping track of DB objects
    tags = {}
    for tag_str in objects['tags']:
        tag = objects['tags'][tag_str]

        tag = Tag(tag)
        tags[tag_str] = tag
        DB.session.add(tag)

    # add Resources, keeping track of DB objects
    resources = {}
    for resource_name in objects['resources']:
        resource = objects['resources'][resource_name]

        resource_tags = []
        for tag_str in resource['tags']:
            resource_tags.append(tags[tag_str])

        resource = Resource(users[resource['owner']],
                            resource['resource_type'],
                            resource['title'],
                            resource['url'],
                            resource_tags)

        resources[resource_name] = resource
        DB.session.add(resource)

    # add Probes, keeping track of DB objects
    probes = {}
    for probe_name in objects['probes']:
        probe = objects['probes'][probe_name]

        probe = Probe(resources[probe['resource']],
                      probe['proberunner'],
                      probe['parameters'],
                      )

        probes[probe_name] = probe
        DB.session.add(probe)

    # add Checks, keeping track of DB objects
    checks = {}
    for check_name in objects['checks']:
        check = objects['checks'][check_name]

        check = Check(probes[check['probe']],
                      check['checker'],
                      check['parameters'],
                      )

        checks[check_name] = check
        DB.session.add(check)

    db_commit()
    DB.session.close()


# commit or rollback shorthand
def db_commit():
    try:
        DB.session.commit()
    except Exception as err:
        DB.session.rollback()
        msg = str(err)
        print(msg)

if __name__ == '__main__':
    import sys
    from flask import Flask
    APP = Flask(__name__)
    APP.config.from_pyfile('config_main.py')
    APP.config.from_pyfile('../instance/config_site.py')


    if len(sys.argv) > 1:
        if sys.argv[1] == 'create':
            print('Creating database objects')
            DB.create_all()

            print('Creating superuser account')
            if len(sys.argv) == 5:  # username/password/email sent
                username = sys.argv[2]
                password1 = sys.argv[3]
                email1 = sys.argv[4]
            else:
                username = raw_input('Enter your username: ').strip()
                password1 = raw_input('Enter your password: ').strip()
                password2 = raw_input('Enter your password again: ').strip()
                if password1 != password2:
                    raise ValueError('Passwords must match')
                email1 = raw_input('Enter your email: ').strip()
                email2 = raw_input('Enter your email again: ').strip()
                if email1 != email2:
                    raise ValueError('Emails must match')

            user_to_add = User(username, password1, email1, role='admin')
            DB.session.add(user_to_add)
            db_commit()
        elif sys.argv[1] == 'drop':
            print('Dropping database objects')
            DB.drop_all()
            db_commit()
        elif sys.argv[1] == 'load':
            print('Load database from JSON file (e.g. tests/fixtures.json)')
            if len(sys.argv) > 2:
                file_path = sys.argv[2]
                yesno = 'n'
                if len(sys.argv) == 3:
                    print('WARNING: all DB data will be lost! Proceed?')
                    yesno = raw_input(
                        'Enter y (proceed) or n (abort): ').strip()
                elif len(sys.argv) == 4:
                    yesno = sys.argv[3]
                else:
                    sys.exit(0)
                    
                if yesno == 'y':
                    print('Loading data....')
                    load_data(file_path)
                    print('Data loaded')
                else:
                    print('Aborted')
            else:
                print('Provide path to JSON file, e.g. tests/fixtures.json')

        elif sys.argv[1] == 'run':
            print('START - Running health check tests on %s'
                  % datetime.utcnow().isoformat())
            from healthcheck import run_test_resource
            for resource in Resource.query.all():  # run all tests
                print('Testing %s %s' %
                      (resource.resource_type, resource.url))

                # Get the status of the last run,
                # assume success if there is none
                last_run_success = True
                last_run = resource.last_run
                if last_run:
                    last_run_success = last_run.success

                # Run test
                run_to_add = run_test_resource(resource)

                run1 = Run(resource, run_to_add[1], run_to_add[2],
                           run_to_add[3], run_to_add[4])

                print('Adding Run: success=%s, response_time=%ss\n'
                      % (str(run1.success), run1.response_time))
                DB.session.add(run1)
                # commit or rollback each run to avoid long-lived transactions
                # see https://github.com/geopython/GeoHealthCheck/issues/14
                db_commit()

                if APP.config['GHC_NOTIFICATIONS']:
                    # Attempt notification
                    try:
                        notify(APP.config, resource, run1, last_run_success)
                    except Exception as err:
                        # Don't bail out on failure in order to commit the Run
                        msg = str(err)
                        print('error notifying: %s' % msg)
            print('END - Running health check tests on %s'
                  % datetime.utcnow().isoformat())
        elif sys.argv[1] == 'flush':
            print('Flushing runs older than %d days' %
                  int(APP.config['GHC_RETENTION_DAYS']))
            for run1 in Run.query.all():
                here_and_now = datetime.utcnow()
                days_old = (here_and_now - run1.checked_datetime).days
                if days_old > APP.config['GHC_RETENTION_DAYS']:
                    print('Run older than %d days. Deleting' % days_old)
                    DB.session.delete(run1)
            db_commit()
