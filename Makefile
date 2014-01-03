mock_server: data/nations.xml data/regions.xml
	./mock_server.py

ratelimited: data/nations.xml data/regions.xml
	./mock_server.py --ratelimited

data/nations.xml:
	ln -s nations-min.xml data/nations.xml

data/regions.xml:
	ln -s regions-min.xml data/regions.xml

