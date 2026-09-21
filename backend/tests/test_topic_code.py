"""TZ 7/8/9 — topic code generation."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.enums import CodeScheme, Gender
from app.services.topic_code import TopicCodeGenerator


async def test_default_prefixes_are_seeded_once(session):
    generator = TopicCodeGenerator(session)
    first = await generator.ensure_default_prefixes()
    second = await generator.ensure_default_prefixes()
    assert len(first) == 2
    assert len(second) == 2
    assert {p.gender for p in first} == {Gender.MALE.value, Gender.FEMALE.value}


async def test_codes_are_sequential_and_unique(session):
    generator = TopicCodeGenerator(session)
    codes = [await generator.next_code(Gender.MALE.value) for _ in range(5)]
    numbers = [generated.sequence for generated in codes]
    assert numbers == [1, 2, 3, 4, 5]
    assert len({generated.code for generated in codes}) == 5


async def test_gender_scheme_uses_different_letter_pools(session):
    generator = TopicCodeGenerator(session)
    male = await generator.next_code(Gender.MALE.value)
    female = await generator.next_code(Gender.FEMALE.value)
    assert male.letter in settings.male_prefix_letters
    assert female.letter in settings.female_prefix_letters
    assert male.letter != female.letter


async def test_letter_rotates_within_pool(session):
    generator = TopicCodeGenerator(session)
    letters = {(await generator.next_code(Gender.MALE.value)).letter for _ in range(13)}
    assert letters == set(settings.male_prefix_letters)


async def test_code_format_matches_spec(session):
    generator = TopicCodeGenerator(session)
    generated = await generator.next_code(Gender.FEMALE.value)
    letter, number = generated.code.split(settings.code_separator)
    assert len(letter) == settings.code_prefix_length
    assert len(number) == settings.code_zero_pad
    assert number.isdigit()


async def test_sequential_scheme_ignores_gender(session, monkeypatch):
    monkeypatch.setattr(settings, "default_code_scheme", CodeScheme.SEQUENTIAL.value)
    generator = TopicCodeGenerator(session)
    male = await generator.next_code(Gender.MALE.value)
    female = await generator.next_code(Gender.FEMALE.value)
    assert male.prefix_id == female.prefix_id
    assert female.sequence == male.sequence + 1


async def test_random_scheme_still_unique(session, monkeypatch):
    monkeypatch.setattr(settings, "default_code_scheme", CodeScheme.RANDOM.value)
    generator = TopicCodeGenerator(session)
    prefixes = await generator.ensure_default_prefixes()
    for prefix in prefixes:
        prefix.mode = CodeScheme.RANDOM.value
    await session.flush()
    codes = [(await generator.next_code(Gender.MALE.value)).code for _ in range(20)]
    assert len(set(codes)) == 20


async def test_prettify(session):
    assert TopicCodeGenerator.prettify("A-0001") == "❤ A001"
    assert TopicCodeGenerator.prettify("M-1002", emoji="") == "M1002"


async def test_gender_pool_is_admin_configurable(session):
    generator = TopicCodeGenerator(session)
    prefixes = await generator.ensure_default_prefixes()
    for prefix in prefixes:
        if prefix.gender == Gender.MALE.value:
            prefix.letters = "XY"
    await session.flush()
    generated = await generator.next_code(Gender.MALE.value)
    assert generated.letter in {"X", "Y"}
