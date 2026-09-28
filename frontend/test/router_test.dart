import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/models/price_history_entry.dart';
import 'package:grocery_receipt/models/product.dart';
import 'package:grocery_receipt/providers/price_history.dart';
import 'package:grocery_receipt/providers/product_detail.dart';
import 'package:grocery_receipt/router.dart';

void main() {
  testWidgets('navigates from the search route to the product detail route', (tester) async {
    addTearDown(() => appRouter.go('/'));

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          productDetailProvider.overrideWith(
            (ref, id) async => Product(id: id, name: 'Producto $id'),
          ),
          priceHistoryProvider.overrideWith((ref, id) async => const <PriceHistoryEntry>[]),
        ],
        child: MaterialApp.router(routerConfig: appRouter),
      ),
    );

    expect(find.text('Escribe para buscar productos.'), findsOneWidget);

    appRouter.push('/product/123');
    await tester.pumpAndSettle();

    expect(find.text('Producto 123'), findsOneWidget);
  });
}
