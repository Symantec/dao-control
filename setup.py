import setuptools

setuptools.setup(
    name='dao.control',
    version='0.7.1',
    namespace_packages=['dao'],
    author='Sergii Kashaba',
    description='Deployment Automation and Orchestration Framework',
    classifiers=[
        'Environment :: Console',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English'
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python',
    ],
    packages=setuptools.find_packages(),
    package_data={'': ['migrate.cfg']},
    install_requires=[
        'eventlet',
        'netaddr',
        'PrettyTable',
        'python-daemon',
        'pyzmq',
        'requests',
        'sqlalchemy',
        'sqlalchemy-migrate'
    ],
    tests_require=['pytest'],
    scripts=['bin/dao-master', 'bin/dao-worker'],
    entry_points={
        'console_scripts':
        ['dao-worker-agent = dao.control.worker.run_manager:run',
         'dao-master-agent = dao.control.master.run_manager:run',
         'dao-config-validate = dao.control.validate_config:main',
         'dao-config-read = dao.control.read_config:main']},
    data_files=[('/etc/dao', ['etc/control.cfg', 'etc/logger.cfg'])]
)
