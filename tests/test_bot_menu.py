import unittest
from bot import keyboards


class BotMenuTests(unittest.TestCase):
    def test_website_is_last_and_mini_app_button_is_removed(self):
        for hidden in (False, True):
            for renew in (False, True):
                for app_url in (None, 'https://t.me/nastaunik_club_bot?startapp'):
                    with self.subTest(hidden=hidden, renew=renew, app_url=app_url):
                        markup = keyboards.main_menu_keyboard(hide_entry_actions=hidden, show_renew_button=renew, mini_app_url=app_url)
                        buttons = [b for row in markup.inline_keyboard for b in row]
                        self.assertFalse(any('Mini App' in b.text for b in buttons))
                        self.assertEqual(sum(b.text == 'Открыть сайт клуба' for b in buttons), 1)
                        website = buttons[-1].model_dump(exclude_none=True)
                        self.assertEqual(website['text'], 'Открыть сайт клуба')
                        self.assertEqual(website['url'], 'https://nastaunik.aiteacher.by/')
                        self.assertEqual(website['style'], 'primary')
                        self.assertNotIn('web_app', website)
                        payment = next(b for b in buttons if b.text == 'Как оплатить')
                        self.assertEqual(payment.callback_data, 'menu:payment')
                        self.assertEqual(payment.model_dump(exclude_none=True)['style'], 'success')
                        join = [b for b in buttons if b.callback_data == 'menu:join']
                        self.assertEqual(len(join), 0 if hidden else 1)
                        if join:
                            self.assertEqual(join[0].text, 'Продлить участие в клубе' if renew else 'Вступить в клуб')

    def test_payment_buttons_are_consistent(self):
        menus = [keyboards.inside_keyboard(), keyboards.trial_finished_keyboard(),
                 keyboards.reminder_keyboard(), keyboards.expired_keyboard()]
        for menu in menus:
            for row in menu.inline_keyboard:
                for button in row:
                    if button.text == 'Как оплатить':
                        self.assertEqual(button.callback_data, 'menu:payment')
                        self.assertEqual(button.model_dump(exclude_none=True)['style'], 'success')
