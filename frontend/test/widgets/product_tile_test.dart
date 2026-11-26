import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/models/product.dart';
import 'package:grocery_receipt/widgets/product_tile.dart';

void main() {
  Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

  testWidgets('renders name, brand and off name', (tester) async {
    const product = Product(
      id: 'p1',
      name: 'Leche',
      brand: 'Hacendado',
      offName: 'Leche entera Hacendado 1L',
    );

    await tester.pumpWidget(wrap(ProductTile(product: product, onTap: () {})));

    expect(find.text('Leche'), findsOneWidget);
    expect(find.text('Hacendado · Leche entera Hacendado 1L'), findsOneWidget);
    expect(find.byIcon(Icons.shopping_bag_outlined), findsOneWidget);
  });

  testWidgets('invokes onTap when tapped', (tester) async {
    var tapped = false;
    const product = Product(id: 'p1', name: 'Leche');

    await tester.pumpWidget(
      wrap(ProductTile(product: product, onTap: () => tapped = true)),
    );
    await tester.tap(find.byType(ListTile));

    expect(tapped, isTrue);
  });
}
