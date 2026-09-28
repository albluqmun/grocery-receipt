import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/models/product.dart';

void main() {
  group('Product.fromJson', () {
    test('parses all fields', () {
      final product = Product.fromJson({
        'id': 'p1',
        'name': 'Leche entera',
        'brand': 'Hacendado',
        'off_name': 'Leche entera Hacendado',
        'off_image_url': 'https://example.com/leche.jpg',
      });

      expect(product.id, 'p1');
      expect(product.name, 'Leche entera');
      expect(product.brand, 'Hacendado');
      expect(product.offName, 'Leche entera Hacendado');
      expect(product.offImageUrl, 'https://example.com/leche.jpg');
    });

    test('parses with optional fields missing', () {
      final product = Product.fromJson({'id': 'p1', 'name': 'Leche entera'});

      expect(product.brand, isNull);
      expect(product.offName, isNull);
      expect(product.offImageUrl, isNull);
    });
  });

  group('displayBrand', () {
    test('returns null when brand is null', () {
      const product = Product(id: 'p1', name: 'Leche');
      expect(product.displayBrand, isNull);
    });

    test('returns null when brand is blank', () {
      const product = Product(id: 'p1', name: 'Leche', brand: '   ');
      expect(product.displayBrand, isNull);
    });

    test('returns brand when present', () {
      const product = Product(id: 'p1', name: 'Leche', brand: 'Hacendado');
      expect(product.displayBrand, 'Hacendado');
    });
  });

  group('displayOffName', () {
    test('returns null when offName is null', () {
      const product = Product(id: 'p1', name: 'Leche');
      expect(product.displayOffName, isNull);
    });

    test('returns null when offName matches name', () {
      const product = Product(id: 'p1', name: 'Leche', offName: 'Leche');
      expect(product.displayOffName, isNull);
    });

    test('returns offName when it differs from name', () {
      const product = Product(
        id: 'p1',
        name: 'Leche',
        offName: 'Leche entera Hacendado 1L',
      );
      expect(product.displayOffName, 'Leche entera Hacendado 1L');
    });
  });
}
