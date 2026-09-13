import unittest
from bot.learning_admin_v2 import clean_rich_text


class CopyBlockTests(unittest.TestCase):
    def test_preserves_plain_text_and_whitespace(self):
        html='<pre>Промпт:\n  &lt;div&gt; &amp; текст\n\nКонец</pre>'
        self.assertEqual(clean_rich_text(html),html)
        self.assertEqual(clean_rich_text(clean_rich_text(html)),html)

    def test_strips_unsafe_attributes_and_scripts(self):
        self.assertEqual(clean_rich_text('<pre onclick="evil()"><code>text</code><script>evil()</script></pre>'),'<pre><code>text</code></pre>')
