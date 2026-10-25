import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'src'))

import unittest

import tr_numbers


class NumberWordsTest(unittest.TestCase):
    def test_cardinal(self):
        self.assertEqual(tr_numbers.cardinal(44), 'kırk dört')
        self.assertEqual(tr_numbers.cardinal(100), 'yüz')
        self.assertEqual(tr_numbers.cardinal(1001), 'bin bir')
        self.assertEqual(tr_numbers.cardinal(2350), 'iki bin üç yüz elli')
        self.assertEqual(tr_numbers.cardinal(1_000_000), 'bir milyon')
        self.assertEqual(tr_numbers.cardinal(120_000), 'yüz yirmi bin')

    def test_ordinal(self):
        self.assertEqual(tr_numbers.ordinal(44), 'kırk dördüncü')
        self.assertEqual(tr_numbers.ordinal(1), 'birinci')
        self.assertEqual(tr_numbers.ordinal(100), 'yüzüncü')
        self.assertEqual(tr_numbers.ordinal(1000), 'bininci')
        self.assertEqual(tr_numbers.ordinal(60), 'altmışıncı')

    def test_roman_value(self):
        self.assertEqual(tr_numbers.roman_value('IV'), 4)
        self.assertEqual(tr_numbers.roman_value('XIX'), 19)
        self.assertIsNone(tr_numbers.roman_value('IIII'))
        self.assertIsNone(tr_numbers.roman_value('M'))     # 'M. Kemal'


class SpokenTest(unittest.TestCase):
    def test_arabic_ordinal(self):
        self.assertEqual(tr_numbers.spoken("Çöküşü'nün 44. bölümünü izliyordum."),
                         "Çöküşü'nün kırk dördüncü bölümünü izliyordum.")
        self.assertEqual(tr_numbers.spoken('"21. yüzyıl" dedi.'), '"Yirmi birinci yüzyıl" dedi.')
        self.assertEqual(tr_numbers.spoken("44'üncü sırada."), 'Kırk dördüncü sırada.')

    def test_roman(self):
        self.assertEqual(tr_numbers.spoken('Sultan IV. Murad ile I. Ahmed'), 'Sultan Dördüncü Murad ile Birinci Ahmed')
        self.assertEqual(tr_numbers.spoken('Bu XV. yüzyıl. II. Dünya Savaşı.'),
                         'Bu on beşinci yüzyıl. İkinci Dünya Savaşı.')

    def test_untouched(self):
        for text in ['Yaşı 44. Sonra gitti.', "1990'da 3.5 kg, 29.10.2026.", 'M. Kemal ve John D. Rockefeller.',
                     'Kırk dört kişi.', 'Saat 10.30 oldu.']:
            self.assertEqual(tr_numbers.spoken(text), text)


if __name__ == '__main__':
    unittest.main()
