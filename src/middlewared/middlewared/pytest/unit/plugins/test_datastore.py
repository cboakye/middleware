from contextlib import asynccontextmanager
from unittest.mock import Mock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base

from middlewared.plugins.datastore import DatastoreService
from middlewared.sqlalchemy import JSON

from middlewared.pytest.unit.middleware import Middleware

Model = declarative_base()


@asynccontextmanager
async def datastore_test():
    m = Middleware()
    with patch("middlewared.plugins.datastore.FREENAS_DATABASE", ":memory:"):
        with patch("middlewared.plugins.datastore.Model", Model):
            ds = DatastoreService(m)
            await ds.setup()
            Model.metadata.create_all(bind=ds.connection)

            yield ds


class UserModel(Model):
    __tablename__ = 'account_bsdusers'

    id = sa.Column(sa.Integer(), primary_key=True)
    bsdusr_uid = sa.Column(sa.Integer(), nullable=False)
    bsdusr_group_id = sa.Column(sa.ForeignKey('account_bsdgroups.id'), nullable=False)


class GroupModel(Model):
    __tablename__ = 'account_bsdgroups'

    id = sa.Column(sa.Integer(), primary_key=True)
    bsdgrp_gid = sa.Column(sa.Integer(), nullable=False)


class GroupMembershipModel(Model):
    __tablename__ = 'account_bsdgroupmembership'

    id = sa.Column(sa.Integer(), primary_key=True)
    bsdgrpmember_group_id = sa.Column(sa.Integer(), sa.ForeignKey("account_bsdgroups.id"), nullable=False)
    bsdgrpmember_user_id = sa.Column(sa.Integer(), sa.ForeignKey("account_bsdusers.id"), nullable=False)


@pytest.mark.asyncio
async def test__relationship_load():
    async with datastore_test() as ds:
        await ds.execute("INSERT INTO `account_bsdgroups` VALUES (10, 1010)")
        await ds.execute("INSERT INTO `account_bsdgroups` VALUES (20, 2020)")
        await ds.execute("INSERT INTO `account_bsdusers` VALUES (5, 55, 20)")
        await ds.execute("INSERT INTO `account_bsdgroupmembership` VALUES (1, 10, 5)")

        assert await ds.query("account.bsdgroupmembership") == [
            {
                "id": 1,
                "bsdgrpmember_group": {
                    "id": 10,
                    "bsdgrp_gid": 1010,
                },
                "bsdgrpmember_user": {
                    "id": 5,
                    "bsdusr_uid": 55,
                    "bsdusr_group": {
                        "id": 20,
                        "bsdgrp_gid": 2020,
                    },
                }
            }
        ]


@pytest.mark.asyncio
async def test__prefix():
    async with datastore_test() as ds:
        await ds.execute("INSERT INTO `account_bsdgroups` VALUES (20, 2020)")
        await ds.execute("INSERT INTO `account_bsdusers` VALUES (5, 55, 20)")

        assert await ds.query("account.bsdusers", [], {"prefix": "bsdusr_"}) == [
            {
                "id": 5,
                "uid": 55,
                "group": {
                    "id": 20,
                    "bsdgrp_gid": 2020,
                },
            }
        ]


@pytest.mark.asyncio
async def test__prefix_filter():
    async with datastore_test() as ds:
        await ds.execute("INSERT INTO `account_bsdgroups` VALUES (20, 2020)")
        await ds.execute("INSERT INTO `account_bsdusers` VALUES (5, 55, 20)")

        assert await ds.query("account.bsdusers", [("uid", "=", 55)], {"prefix": "bsdusr_"}) == [
            {
                "id": 5,
                "uid": 55,
                "group": {
                    "id": 20,
                    "bsdgrp_gid": 2020,
                },
            }
        ]
        assert await ds.query("account.bsdusers", [("uid", "=", 56)], {"prefix": "bsdusr_"}) == []

        with pytest.raises(Exception):
            assert await ds.query("account.bsdusers", [("bsdusr_uid", "=", 55)], {"prefix": "bsdusr_"})


class NullableFkModel(Model):
    __tablename__ = 'test_nullablefk'

    id = sa.Column(sa.Integer(), primary_key=True)
    user_id = sa.Column(sa.Integer(), sa.ForeignKey("account_bsdusers.id"), nullable=True)


@pytest.mark.asyncio
async def test__relationship_load():
    async with datastore_test() as ds:
        await ds.execute("INSERT INTO `test_nullablefk` VALUES (1, NULL)")

        assert await ds.query("test.nullablefk") == [
            {
                "id": 1,
                "user": None,
            }
        ]


class StringModel(Model):
    __tablename__ = 'test_string'

    id = sa.Column(sa.Integer(), primary_key=True)
    string = sa.Column(sa.String(100))


@pytest.mark.parametrize("filter,ids", [
    ([("string", "~", "(e|u)m")], [1, 2]),
    ([("string", "~", "L?rem")], [1]),

    ([("string", "in", ["Ipsum", "dolor"])], [2]),
    ([("string", "nin", ["Ipsum", "dolor"])], [1]),

    ([("string", "^", "Lo")], [1]),
    ([("string", "$", "um")], [2]),
])
@pytest.mark.asyncio
async def test__string_filters(filter, ids):
    async with datastore_test() as ds:
        await ds.execute("INSERT INTO test_string VALUES (1, 'Lorem')")
        await ds.execute("INSERT INTO test_string VALUES (2, 'Ipsum')")

        assert [row["id"] for row in await ds.query("test.string", filter)] == ids


class IntegerModel(Model):
    __tablename__ = 'test_integer'

    id = sa.Column(sa.Integer(), primary_key=True)
    integer = sa.Column(sa.Integer())


@pytest.mark.parametrize("filter,ids", [
    ([("integer", ">", 1), ("integer", "<", 5)], [2, 3, 4]),
    ([("OR", [("integer", ">=", 4), ("integer", "<=", 2)])], [1, 2, 4, 5]),
])
@pytest.mark.asyncio
async def test__logic(filter, ids):
    async with datastore_test() as ds:
        await ds.execute("INSERT INTO test_integer VALUES (1, 1)")
        await ds.execute("INSERT INTO test_integer VALUES (2, 2)")
        await ds.execute("INSERT INTO test_integer VALUES (3, 3)")
        await ds.execute("INSERT INTO test_integer VALUES (4, 4)")
        await ds.execute("INSERT INTO test_integer VALUES (5, 5)")

        assert [row["id"] for row in await ds.query("test.integer", filter)] == ids


class JSONModel(Model):
    __tablename__ = 'test_json'

    id = sa.Column(sa.Integer(), primary_key=True)
    object = sa.Column(JSON())


@pytest.mark.parametrize("string,object", [
    ('{"key": "value"}', {"key": "value"}),
    ('{"key": "value"', {}),
])
@pytest.mark.asyncio
async def test__json_load(string, object):
    async with datastore_test() as ds:
        await ds.execute("INSERT INTO test_json VALUES (1, ?)", string)

        assert (await ds.query("test.json", [], {"get": True}))["object"] == object


@pytest.mark.asyncio
async def test__json_save():
    async with datastore_test() as ds:
        await ds.insert("test.json", {"object": {"key": "value"}})
        assert (await ds.sql("SELECT * FROM test_json"))[0]["object"] == '{"key": "value"}'


class EncryptedJSONModel(Model):
    __tablename__ = 'test_encryptedjson'

    id = sa.Column(sa.Integer(), primary_key=True)
    object = sa.Column(JSON(encrypted=True))


def decrypt(s, _raise=False):
    assert _raise is True

    if not s.startswith("!"):
        raise Exception("Decryption failed")

    return s[1:]


def encrypt(s):
    return f"!{s}"


@pytest.mark.parametrize("string,object", [
    ('!{"key":"value"}', {"key": "value"}),
    ('!{"key":"value"', {}),
    ('{"key":"value"}', {}),
])
@pytest.mark.asyncio
async def test__encrypted_json_load(string, object):
    async with datastore_test() as ds:
        await ds.execute("INSERT INTO test_encryptedjson VALUES (1, ?)", string)

        with patch("middlewared.sqlalchemy.decrypt", decrypt):
            assert (await ds.query("test.encryptedjson", [], {"get": True}))["object"] == object


@pytest.mark.asyncio
async def test__encrypted_json_save():
    async with datastore_test() as ds:
        with patch("middlewared.sqlalchemy.encrypt", encrypt):
            await ds.insert("test.encryptedjson", {"object": {"key": "value"}})

        assert (await ds.sql("SELECT * FROM test_encryptedjson"))[0]["object"] == '!{"key": "value"}'
