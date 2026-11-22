import unittest
from decimal import Decimal
from engine import parse_sale


class TestEngine(unittest.TestCase):
    def test_normal_sale(self):
        tx = parse_sale('Musa bought goods worth 15,000 naira. He paid 10,000 naira.')
        self.assertEqual(tx.customer, 'Musa')
        self.assertEqual(tx.balance, Decimal('5000'))

    def test_full_payment(self):
        tx = parse_sale('Amina bought rice worth 5000 naira. She paid 5000 naira.')
        self.assertEqual(tx.balance, Decimal('0'))

    def test_overpayment_rejected(self):
        with self.assertRaises(ValueError):
            parse_sale('Musa bought goods worth 5000 naira. He paid 6000 naira.')

    def test_unsupported_rejected(self):
        with self.assertRaises(ValueError):
            parse_sale('I bought two bags of rice')


if __name__ == '__main__':
    unittest.main()
