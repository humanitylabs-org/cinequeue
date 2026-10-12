import unittest

from cinequeue.enrich import merge_letterboxd_details, parse_letterboxd_details


class LetterboxdDetailsParserTest(unittest.TestCase):
    def test_extracts_metadata_and_external_ids_without_importing_letterboxd_score(self):
        html = '''
        <section class="production-synopsis"><div class="review body-text -prose -hero prettify">
          <h4 class="tagline">Never be tempted.</h4>
          <div class="truncate" data-truncate="450"><p>A stranger arrives in a little village.</p></div>
        </div></section>
        <p class="trailer-link js-watch-panel-trailer">
          <a class="play" href="//www.youtube.com/embed/VUWAgbXSJ4Y?rel=0&amp;wmode=transparent"><span>Trailer</span></a>
        </p>
        <p class="text-link text-footer"> 156&nbsp;mins &nbsp; More at <a href="https://www.imdb.com/title/tt5215952/">IMDb</a></p>
        <script type="application/ld+json">/* <![CDATA[ */
        {"@type":"Movie","name":"The Wailing","image":"poster.jpg","genre":["Horror","Mystery"],
         "director":[{"@type":"Person","name":"Na Hong-jin"}],
         "actors":[{"@type":"Person","name":"Kwak Do-won"},{"@type":"Person","name":"Hwang Jung-min"},{"@type":"Person","name":"Chun Woo-hee"},{"@type":"Person","name":"Jun Kunimura"}],
         "aggregateRating":{"ratingValue":3.98,"ratingCount":302326}}
        /* ]]> */</script>
        '''

        details = parse_letterboxd_details(html)

        self.assertEqual(details["description"], "A stranger arrives in a little village.")
        self.assertEqual(details["genres"], ["Horror", "Mystery"])
        self.assertEqual(details["directors"], ["Na Hong-jin"])
        self.assertEqual(details["cast"], ["Kwak Do-won", "Hwang Jung-min", "Chun Woo-hee"])
        self.assertEqual(details["imdb_id"], "tt5215952")
        self.assertEqual(details["imdb_url"], "https://www.imdb.com/title/tt5215952/")
        self.assertNotIn("rating", details)
        self.assertNotIn("rating_count", details)
        self.assertEqual(details["runtime_minutes"], 156)
        self.assertEqual(details["trailer_url"], "https://www.youtube.com/watch?v=VUWAgbXSJ4Y")

    def test_rejects_page_with_multiple_distinct_imdb_links(self):
        source = '''
        <a href="https://www.imdb.com/title/tt1234567/">One</a>
        <a href="https://www.imdb.com/title/tt7654321/">Two</a>
        '''
        details = parse_letterboxd_details(source)

        self.assertEqual(details["imdb_id"], "")
        self.assertEqual(details["imdb_url"], "")

    def test_identity_change_clears_stale_imdb_score(self):
        movie = {
            "id": "film",
            "imdb_id": "tt1234567",
            "rating": 8.4,
            "rating_count": 1234,
            "rating_source": "imdb",
            "poster": "keep.jpg",
        }

        merge_letterboxd_details(
            movie,
            {"imdb_id": "tt7654321", "imdb_url": "https://www.imdb.com/title/tt7654321/", "poster": "replace.jpg"},
        )

        self.assertEqual(movie["imdb_id"], "tt7654321")
        self.assertEqual(movie["poster"], "keep.jpg")
        self.assertNotIn("rating", movie)
        self.assertNotIn("rating_count", movie)
        self.assertNotIn("rating_source", movie)


if __name__ == "__main__":
    unittest.main()
