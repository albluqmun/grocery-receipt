import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/models/price_history_entry.dart';
import 'package:grocery_receipt/models/product.dart';
import 'package:grocery_receipt/providers/price_history.dart';
import 'package:grocery_receipt/providers/product_detail.dart';
import 'package:grocery_receipt/screens/product_screen.dart';

void main() {
  const productId = 'p1';

  Future<void> pumpScreen(
    WidgetTester tester, {
    required List<Override> overrides,
  }) {
    return tester.pumpWidget(
      ProviderScope(
        overrides: overrides,
        child: const MaterialApp(home: ProductScreen(productId: productId)),
      ),
    );
  }

  testWidgets('shows a loading indicator while the product is loading', (tester) async {
    final neverCompletes = Completer<Product>();
    addTearDown(() => neverCompletes.complete(const Product(id: productId, name: 'Leche')));

    await pumpScreen(
      tester,
      overrides: [
        productDetailProvider.overrideWith((ref, id) => neverCompletes.future),
        priceHistoryProvider.overrideWith((ref, id) async => const <PriceHistoryEntry>[]),
      ],
    );
    await tester.pump();

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('shows product details and price history when loaded', (tester) async {
    await pumpScreen(
      tester,
      overrides: [
        productDetailProvider.overrideWith(
          (ref, id) async =>
              const Product(id: productId, name: 'Leche entera', brand: 'Hacendado'),
        ),
        priceHistoryProvider.overrideWith(
          (ref, id) async => [
            PriceHistoryEntry(
              date: DateTime(2026, 4, 10),
              supermarketName: 'Mercadona',
              unitPrice: 1.35,
            ),
          ],
        ),
      ],
    );
    await tester.pumpAndSettle();

    expect(find.text('Leche entera'), findsOneWidget);
    expect(find.text('Hacendado'), findsOneWidget);
    expect(find.text('Mercadona'), findsOneWidget);
    expect(find.byIcon(Icons.shopping_bag_outlined), findsOneWidget);
  });

  testWidgets('shows a friendly message when the product fails to load', (tester) async {
    await pumpScreen(
      tester,
      overrides: [
        productDetailProvider.overrideWith((ref, id) async => throw Exception('boom')),
        priceHistoryProvider.overrideWith((ref, id) async => const <PriceHistoryEntry>[]),
      ],
    );
    await tester.pumpAndSettle();

    expect(find.text('Ha ocurrido un error inesperado.'), findsOneWidget);
  });
}
