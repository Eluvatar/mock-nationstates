mock-nationstates
================

Mock NS API for testing or other purposes

To use minimally:

`make`

To use with actual data:

1. obtain uncompressed full regions.xml and nations.xml and put them in data/ (optionally name them something else and symlink appropriately).
2. `./mock_server.py` or `make`

The mock server will be available at [http://localhost:6260/cgi-bin/api.cgi](http://localhost:6260/cgi-bin/api.cgi)
