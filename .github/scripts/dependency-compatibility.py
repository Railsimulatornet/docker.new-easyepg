"""Offline regression checks against a pinned EasyEPG source checkout."""
import ast
import base64
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import importlib.util
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

import requests
import simplejson
import xmltodict

SOURCE = Path(os.environ['EASYEPG_SOURCE'])
OBSERVATIONS = {}


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 9, 27, 12, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    @classmethod
    def today(cls):
        return cls.now()


def load_provider():
    path = SOURCE / 'resources/lib/providers/xmltv.py'
    spec = importlib.util.spec_from_file_location('xmltv_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.datetime = FixedDateTime
    return module


def load_grabber_class():
    # Execute the original class unchanged, without importing startup services.
    path = SOURCE / 'resources/lib/epg.py'
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Grabber']
    if len(classes) != 1:
        raise AssertionError('Expected one upstream Grabber class')
    namespace = dict(datetime=FixedDateTime, timezone=timezone, base64=base64,
                     gzip=gzip, json=json, os=os, shutil=shutil, time=time,
                     traceback=traceback, xmltodict=xmltodict, sleep=lambda _: None,
                     basedir=SimpleNamespace(get_path=lambda name, root: str(Path(root) / name)))
    exec(compile(ast.Module(body=classes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['Grabber']


def canonical_xml(element):
    return {'tag': element.tag, 'attributes': dict(element.attrib),
            'text': (element.text or '').strip(),
            'children': [canonical_xml(child) for child in element]}


class XMLCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = load_provider()
        cls.grabber = load_grabber_class()

    def test_channel_import(self):
        examples = [
            '<channel id="one"><display-name lang="de">Kultur &amp; Musik</display-name><icon src="icon.png"/></channel>',
            '<channel id="one"><display-name lang="de">Kultur &amp; Musik</display-name><display-name lang="en">Culture</display-name><icon src="first.png"/><icon src="second.png"/></channel>\n<channel id="two"><display-name>Nachrichten</display-name></channel>',
        ]
        for index, channels in enumerate(examples):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'channels.xml'
                path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE tv SYSTEM "xmltv.dtd">\n<tv>\n' + channels + '\n<programme channel="one"/>\n</tv>', encoding='utf-8')
                result = self.provider.channels({'url': str(path)}, None)
                self.assertEqual(result['one']['name'], 'Kultur & Musik')
                self.assertEqual(len(result), index + 1)
                OBSERVATIONS['channels_' + str(index)] = result

    def test_programme_import(self):
        source = '''<tv>
<programme channel="one" start="20260927120000 +0000" stop="20260927130000 +0000">
<title lang="de">Grüße &amp; Musik</title><sub-title lang="de">Folge 3</sub-title>
<desc lang="de">Text &lt;mit&gt; Details</desc><icon src="icon.png"/>
<credits><director>Regie</director><actor role="Test">Darsteller</actor><actor>Besetzung</actor></credits>
<category lang="de">Kultur</category><category lang="en">Music</category>
<country>DE</country><country lang="de">AT</country><date>2026</date>
<episode-num system="xmltv_ns">1 . 2 . </episode-num><rating system="FSK"><value>6</value></rating>
<star-rating system="Test"><value>4/5</value></star-rating></programme>
<programme channel="one" start="20260927130000 +0000" stop="20260927140000 +0000"><title>Nachrichten</title></programme>
</tv>'''
        result = self.provider.epg_main_converter(source, {}, ['one'], {'days': '2'})
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['title'], 'Grüße & Musik')
        self.assertEqual(result[0]['credits']['actor'], ['Darsteller', 'Besetzung'])
        self.assertEqual(result[0]['season_episode_num'], {'season': 2, 'episode': 3})
        OBSERVATIONS['programmes'] = result

    def test_original_grabber_export(self):
        double = lambda obj: json.dumps(json.dumps(obj, ensure_ascii=False))
        epoch = int(datetime(2026, 9, 27, 12, tzinfo=timezone.utc).timestamp())
        rows = [
            ('one', 'b1', epoch, epoch + 3600, 'Grüße & <Musik>', 'Folge 3', 'Beschreibung',
             'image.png', '2026', 'DE', double({'system': 'Test', 'value': '4/5'}),
             double({'system': 'FSK', 'value': 6}), double({'director': ['Regie'], 'actor': []}),
             double({'season': 2, 'episode': 3}), double(['Kultur']), ['New', 'Live', 'Premiere'], None),
            ('one', 'b2', epoch + 3600, epoch + 7200, None, None, None, None, None, None,
             None, None, None, None, None, [], None),
        ]
        for mode in ('none', 'add-cast', 'add-info-cast'):
            for batch in (1, 10):
                with self.subTest(mode=mode, batch=batch), tempfile.TemporaryDirectory() as tmp:
                    (Path(tmp) / 'xml').mkdir()
                    calls = []
                    obj = self.grabber.__new__(self.grabber)
                    obj.file_paths = {'storage': tmp}
                    obj.cancellation = obj.exit = False
                    obj.grabbing = obj.started = True
                    obj.pr = SimpleNamespace(providers={'fixture': {'is_utc': True}},
                        main_downloader=lambda provider: calls.append(provider),
                        epg_db=SimpleNamespace(retrieve_epg_db_items=lambda *_: rows))
                    obj.user_db = SimpleNamespace(main={
                        'settings': {'rm': mode, 'pn_max': batch, 'live_title': True},
                        'channels': {'fixture_one': {'stationId': 'one', 'tvg-id': 'one',
                            'name': 'Kultur &amp; Musik', 'preferredImage': {'uri': 'icon.png'}}}},
                        genres={'genres': {'Kultur': 'Culture'}})
                    obj.grabber_process()
                    errors = Path(tmp) / 'grabber_error_log.txt'
                    self.assertFalse(errors.exists(), errors.read_text() if errors.exists() else '')
                    xml = (Path(tmp) / 'xml/epg.xml').read_bytes()
                    root = ET.fromstring(xml)
                    self.assertEqual(calls, ['fixture'])
                    self.assertEqual(len(root.findall('channel')), 1)
                    self.assertEqual(len(root.findall('programme')), 2)
                    self.assertEqual(root.find('programme/title').text, '[LIVE] Grüße & <Musik>')
                    self.assertIsNotNone(root.find('programme/new'))
                    self.assertIsNotNone(root.find('programme/live'))
                    self.assertEqual(root.findall('programme')[1].find('title').text, 'No programme title available')
                    with gzip.open(Path(tmp) / 'xml/epg.xml.gz', 'rb') as file:
                        self.assertEqual(file.read(), xml)
                    OBSERVATIONS[f'export_{mode}_{batch}'] = canonical_xml(root)


class JSONCompatibility(unittest.TestCase):
    def test_requests_backend(self):
        self.assertIs(requests.compat.json, simplejson)
        self.assertIs(requests.models.complexjson, simplejson)

    def test_provider_payloads(self):
        payload = {'channels': [{'id': 1, 'name': 'Kultur & Grüße', 'enabled': True}],
                   'programmes': [{'start': 1790510400, 'title': 'Überblick', 'rating': 4.5}],
                   'next': None}
        for accelerated in (False, True):
            simplejson._toggle_speedups(accelerated)
            for indent in (None, 0, 2):
                with self.subTest(accelerated=accelerated, indent=indent):
                    encoded = simplejson.dumps(payload, ensure_ascii=False, indent=indent)
                    self.assertEqual(simplejson.loads(encoded), payload)
                    for encoding in ('utf-8', 'utf-16'):
                        response = requests.Response()
                        response.status_code = 200
                        response._content = encoded.encode(encoding)
                        response.encoding = encoding
                        self.assertEqual(response.json(), payload)
                    prepared = requests.Request('POST', 'https://example.invalid/', json=payload).prepare()
                    self.assertEqual(simplejson.loads(prepared.body), payload)
                    OBSERVATIONS[f'json_{accelerated}_{indent}'] = encoded
        simplejson._toggle_speedups(True)

    def test_requests_invalid_json_exception(self):
        response = requests.Response()
        response._content = b'{invalid}'
        response.encoding = 'utf-8'
        with self.assertRaises(requests.exceptions.JSONDecodeError):
            response.json()

    def test_numbers_and_unicode(self):
        payload = {'number': 2**63, 'decimal': Decimal('4.125'), 'name': 'Grüße 😀'}
        encoded = simplejson.dumps(payload, use_decimal=True, ensure_ascii=False)
        self.assertEqual(simplejson.loads(encoded, use_decimal=True), payload)
        OBSERVATIONS['numbers'] = encoded


if __name__ == '__main__':
    os.environ['TZ'] = 'UTC'
    if hasattr(time, 'tzset'):
        time.tzset()
    print(json.dumps({'python': sys.version, 'xmltodict': version('xmltodict'),
                      'simplejson': version('simplejson'), 'requests': version('requests'),
                      'native_simplejson': importlib.util.find_spec('simplejson._speedups') is not None}))
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print('SNAPSHOT_JSON=' + json.dumps(OBSERVATIONS, sort_keys=True, ensure_ascii=False))
