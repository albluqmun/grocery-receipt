import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/models/price_history_entry.dart';

void main() {
  group('PriceHistoryEntry.fromJson', () {
    test('parses date, supermarket and numeric unit_price', () {
      final entry = PriceHistoryEntry.fromJson({
        'date': '2026-04-10',
        'supermarket_name': 'Mercadona',
        'unit_price': 1.35,
      });

      expect(entry.date, DateTime(2026, 4, 10));
      expect(entry.supermarketName, 'Mercadona');
      expect(entry.unitPrice, 1.35);
    });

    test('parses unit_price given as a string', () {
      final entry = PriceHistoryEntry.fromJson({
        'date': '2026-04-10',
        'supermarket_name': 'Mercadona',
        'unit_price': '1.35',
      });

      expect(entry.unitPrice, 1.35);
    });
  });
}
