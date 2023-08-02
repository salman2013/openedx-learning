""" Test the tagging APIs """

from django.test.testcases import TestCase, override_settings

import openedx_tagging.core.tagging.api as tagging_api
from openedx_tagging.core.tagging.models import ObjectTag, Tag

from .test_models import TestTagTaxonomyMixin, get_tag

test_languages = [
    ("az", "Azerbaijani"),
    ("en", "English"),
    ("id", "Indonesian"),
    ("qu", "Quechua"),
    ("zu", "Zulu"),
]


class TestApiTagging(TestTagTaxonomyMixin, TestCase):
    """
    Test the Tagging API methods.
    """

    def test_create_taxonomy(self):
        params = {
            "name": "Difficulty",
            "description": "This taxonomy contains tags describing the difficulty of an activity",
            "enabled": False,
            "required": True,
            "allow_multiple": True,
            "allow_free_text": True,
        }
        taxonomy = tagging_api.create_taxonomy(**params)
        for param, value in params.items():
            assert getattr(taxonomy, param) == value
        assert not taxonomy.system_defined
        assert taxonomy.visible_to_authors

    def test_bad_taxonomy_class(self):
        with self.assertRaises(ValueError) as exc:
            tagging_api.create_taxonomy(
                name="Bad class",
                taxonomy_class=str,
            )
        assert "<class 'str'> must be a subclass of Taxonomy" in str(exc.exception)

    def test_get_taxonomy(self):
        tax1 = tagging_api.get_taxonomy(1)
        assert tax1 == self.taxonomy
        no_tax = tagging_api.get_taxonomy(10)
        assert no_tax is None

    def test_get_taxonomies(self):
        tax1 = tagging_api.create_taxonomy("Enabled")
        tax2 = tagging_api.create_taxonomy("Disabled", enabled=False)
        with self.assertNumQueries(1):
            enabled = list(tagging_api.get_taxonomies())

        assert enabled == [
            tax1,
            self.language_taxonomy,
            self.taxonomy,
            self.system_taxonomy,
            self.user_taxonomy,
        ]
        assert str(enabled[0]) == f"<Taxonomy> ({tax1.id}) Enabled"
        assert str(enabled[1]) == "<Taxonomy> (-1) Languages"
        assert str(enabled[2]) == "<Taxonomy> (1) Life on Earth"
        assert str(enabled[3]) == "<SystemDefinedTaxonomy> (4) System defined taxonomy"

        with self.assertNumQueries(1):
            disabled = list(tagging_api.get_taxonomies(enabled=False))
        assert disabled == [tax2]
        assert str(disabled[0]) == f"<Taxonomy> ({tax2.id}) Disabled"

        with self.assertNumQueries(1):
            both = list(tagging_api.get_taxonomies(enabled=None))
        assert both == [
            tax2,
            tax1,
            self.language_taxonomy,
            self.taxonomy,
            self.system_taxonomy,
            self.user_taxonomy,
        ]

    @override_settings(LANGUAGES=test_languages)
    def test_get_tags(self):
        self.setup_tag_depths()
        assert tagging_api.get_tags(self.taxonomy) == [
            *self.domain_tags,
            *self.kingdom_tags,
            *self.phylum_tags,
        ]
        assert tagging_api.get_tags(self.system_taxonomy) == self.system_tags
        tags = tagging_api.get_tags(self.language_taxonomy)
        langs = [tag.external_id for tag in tags]
        expected_langs = [lang[0] for lang in test_languages]
        assert langs == expected_langs

    def check_object_tag(self, object_tag, taxonomy, tag, name, value):
        """
        Verifies that the properties of the given object_tag (once refreshed from the database) match those given.
        """
        object_tag.refresh_from_db()
        assert object_tag.taxonomy == taxonomy
        assert object_tag.tag == tag
        assert object_tag.name == name
        assert object_tag.value == value

    def test_resync_object_tags(self):
        missing_links = ObjectTag.objects.create(
            object_id="abc",
            _name=self.taxonomy.name,
            _value=self.mammalia.value,
        )
        changed_links = ObjectTag.objects.create(
            object_id="def",
            taxonomy=self.taxonomy,
            tag=self.mammalia,
        )
        changed_links.name = "Life"
        changed_links.value = "Animals"
        changed_links.save()
        no_changes = ObjectTag.objects.create(
            object_id="ghi",
            taxonomy=self.taxonomy,
            tag=self.mammalia,
        )
        no_changes.name = self.taxonomy.name
        no_changes.value = self.mammalia.value
        no_changes.save()

        changed = tagging_api.resync_object_tags()
        assert changed == 2
        for object_tag in (missing_links, changed_links, no_changes):
            self.check_object_tag(
                object_tag, self.taxonomy, self.mammalia, "Life on Earth", "Mammalia"
            )

        # Once all tags are resynced, they stay that way
        changed = tagging_api.resync_object_tags()
        assert changed == 0

        # Resync will use the tag's taxonomy if possible
        changed_links.taxonomy = None
        changed_links.save()
        changed = tagging_api.resync_object_tags()
        assert changed == 1
        for object_tag in (missing_links, changed_links, no_changes):
            self.check_object_tag(
                object_tag, self.taxonomy, self.mammalia, "Life on Earth", "Mammalia"
            )

        # Resync will use the taxonomy's tags if possible
        changed_links.tag = None
        changed_links.value = "Xenomorph"
        changed_links.save()
        changed = tagging_api.resync_object_tags()
        assert changed == 0
        changed_links.value = "Mammalia"
        changed_links.save()

        # ObjectTag value preserved even if linked tag is deleted
        self.mammalia.delete()
        for object_tag in (missing_links, changed_links, no_changes):
            self.check_object_tag(
                object_tag, self.taxonomy, None, "Life on Earth", "Mammalia"
            )
        # Recreating the tag to test resyncing works
        new_mammalia = Tag.objects.create(
            value="Mammalia",
            taxonomy=self.taxonomy,
        )
        changed = tagging_api.resync_object_tags()
        assert changed == 3
        for object_tag in (missing_links, changed_links, no_changes):
            self.check_object_tag(
                object_tag, self.taxonomy, new_mammalia, "Life on Earth", "Mammalia"
            )

        # ObjectTag name preserved even if linked taxonomy and its tags are deleted
        self.taxonomy.delete()
        for object_tag in (missing_links, changed_links, no_changes):
            self.check_object_tag(object_tag, None, None, "Life on Earth", "Mammalia")

        # Resyncing the tags for code coverage
        changed = tagging_api.resync_object_tags()
        assert changed == 0

        # Recreate the taxonomy and resync some tags
        first_taxonomy = tagging_api.create_taxonomy(
            "Life on Earth", allow_free_text=True
        )
        second_taxonomy = tagging_api.create_taxonomy("Life on Earth")
        new_tag = Tag.objects.create(
            value="Mammalia",
            taxonomy=second_taxonomy,
        )

        # Ensure the resync prefers the closed taxonomy with the matching tag
        changed = tagging_api.resync_object_tags(
            ObjectTag.objects.filter(object_id__in=["abc", "def"])
        )
        assert changed == 2

        for object_tag in (missing_links, changed_links):
            self.check_object_tag(
                object_tag, second_taxonomy, new_tag, "Life on Earth", "Mammalia"
            )

        # Ensure the omitted tag was not updated
        self.check_object_tag(no_changes, None, None, "Life on Earth", "Mammalia")

        # Update that one too, to demonstrate the free-text tags are ok
        no_changes.value = "Anamelia"
        no_changes.save()
        changed = tagging_api.resync_object_tags(
            ObjectTag.objects.filter(id=no_changes.id)
        )
        assert changed == 1
        self.check_object_tag(
            no_changes, first_taxonomy, None, "Life on Earth", "Anamelia"
        )

    def test_tag_object(self):
        self.taxonomy.allow_multiple = True
        self.taxonomy.save()
        test_tags = [
            [
                self.archaea.id,
                self.eubacteria.id,
                self.chordata.id,
            ],
            [
                self.chordata.id,
                self.archaebacteria.id,
            ],
            [
                self.archaebacteria.id,
                self.archaea.id,
            ],
        ]

        # Tag and re-tag the object, checking that the expected tags are returned and deleted
        for tag_list in test_tags:
            object_tags = tagging_api.tag_object(
                self.taxonomy,
                tag_list,
                "biology101",
            )

            # Ensure the expected number of tags exist in the database
            assert (
                list(
                    tagging_api.get_object_tags(
                        taxonomy=self.taxonomy,
                        object_id="biology101",
                    )
                )
                == object_tags
            )
            # And the expected number of tags were returned
            assert len(object_tags) == len(tag_list)
            for index, object_tag in enumerate(object_tags):
                assert object_tag.tag_id == tag_list[index]
                assert object_tag.is_valid()
                assert object_tag.taxonomy == self.taxonomy
                assert object_tag.name == self.taxonomy.name
                assert object_tag.object_id == "biology101"

    def test_tag_object_free_text(self):
        self.taxonomy.allow_free_text = True
        self.taxonomy.save()
        object_tags = tagging_api.tag_object(
            self.taxonomy,
            ["Eukaryota Xenomorph"],
            "biology101",
        )
        assert len(object_tags) == 1
        object_tag = object_tags[0]
        assert object_tag.is_valid()
        assert object_tag.taxonomy == self.taxonomy
        assert object_tag.name == self.taxonomy.name
        assert object_tag.tag_ref == "Eukaryota Xenomorph"
        assert object_tag.get_lineage() == ["Eukaryota Xenomorph"]
        assert object_tag.object_id == "biology101"

    def test_tag_object_no_multiple(self):
        with self.assertRaises(ValueError) as exc:
            tagging_api.tag_object(
                self.taxonomy,
                ["A", "B"],
                "biology101",
            )
        assert "only allows one tag per object" in str(exc.exception)

    def test_tag_object_required(self):
        self.taxonomy.required = True
        self.taxonomy.save()
        with self.assertRaises(ValueError) as exc:
            tagging_api.tag_object(
                self.taxonomy,
                [],
                "biology101",
            )
        assert "requires at least one tag per object" in str(exc.exception)

    def test_tag_object_invalid_tag(self):
        with self.assertRaises(ValueError) as exc:
            tagging_api.tag_object(
                self.taxonomy,
                ["Eukaryota Xenomorph"],
                "biology101",
            )
        assert "Invalid object tag for taxonomy (1): Eukaryota Xenomorph" in str(
            exc.exception
        )

    @override_settings(LANGUAGES=test_languages)
    def test_tag_object_language_taxonomy(self):
        tags_list = [
            [get_tag("Azerbaijani").id],
            [get_tag("English").id],
        ]

        for tags in tags_list:
            object_tags = tagging_api.tag_object(
                self.language_taxonomy,
                tags,
                "biology101",
            )

            # Ensure the expected number of tags exist in the database
            assert (
                list(
                    tagging_api.get_object_tags(
                        taxonomy=self.language_taxonomy,
                        object_id="biology101",
                    )
                )
                == object_tags
            )
            # And the expected number of tags were returned
            assert len(object_tags) == len(tags)
            for index, object_tag in enumerate(object_tags):
                assert object_tag.tag_id == tags[index]
                assert object_tag.is_valid()
                assert object_tag.taxonomy == self.language_taxonomy
                assert object_tag.name == self.language_taxonomy.name
                assert object_tag.object_id == "biology101"

    @override_settings(LANGUAGES=test_languages)
    def test_tag_object_language_taxonomy_ivalid(self):
        tags = [get_tag("Spanish").id]
        with self.assertRaises(ValueError) as exc:
            tagging_api.tag_object(
                self.language_taxonomy,
                tags,
                "biology101",
            )
        assert "Invalid object tag for taxonomy (-1): -40" in str(
            exc.exception
        )

    def test_tag_object_model_system_taxonomy(self):
        users = [
            self.user_1,
            self.user_2,
        ]

        for user in users:
            tags = [user.id]
            object_tags = tagging_api.tag_object(
                self.user_taxonomy,
                tags,
                "biology101",
            )

            # Ensure the expected number of tags exist in the database
            assert (
                list(
                    tagging_api.get_object_tags(
                        taxonomy=self.user_taxonomy,
                        object_id="biology101",
                    )
                )
                == object_tags
            )
            # And the expected number of tags were returned
            assert len(object_tags) == len(tags)
            for object_tag in object_tags:
                assert object_tag.tag.external_id == str(user.id)
                assert object_tag.tag.value == user.username
                assert object_tag.is_valid()
                assert object_tag.taxonomy == self.user_taxonomy
                assert object_tag.name == self.user_taxonomy.name
                assert object_tag.object_id == "biology101"

    def test_tag_object_model_system_taxonomy_invalid(self):
        tags = ["Invalid id"]
        with self.assertRaises(ValueError) as exc:
            tagging_api.tag_object(
                self.user_taxonomy,
                tags,
                "biology101",
            )
        assert "Invalid object tag for taxonomy (3): Invalid id" in str(
            exc.exception
        )

    def test_get_object_tags(self):
        # Alpha tag has no taxonomy
        alpha = ObjectTag(object_id="abc")
        alpha.name = self.taxonomy.name
        alpha.value = self.mammalia.value
        alpha.save()
        # Beta tag has a closed taxonomy
        beta = ObjectTag.objects.create(
            object_id="abc",
            taxonomy=self.taxonomy,
        )

        # Fetch all the tags for a given object ID
        assert list(
            tagging_api.get_object_tags(
                object_id="abc",
                valid_only=False,
            )
        ) == [
            alpha,
            beta,
        ]

        # No valid tags for this object yet..
        assert not list(
            tagging_api.get_object_tags(
                object_id="abc",
                valid_only=True,
            )
        )
        beta.tag = self.mammalia
        beta.save()
        assert list(
            tagging_api.get_object_tags(
                object_id="abc",
                valid_only=True,
            )
        ) == [
            beta,
        ]

        # Fetch all the tags for a given object ID + taxonomy
        assert list(
            tagging_api.get_object_tags(
                object_id="abc",
                taxonomy=self.taxonomy,
                valid_only=False,
            )
        ) == [
            beta,
        ]
