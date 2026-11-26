import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:grocery_receipt/models/product.dart';
import 'package:grocery_receipt/providers/product_search.dart';
import 'package:grocery_receipt/screens/search_screen.dart';

void main() {
  Future<void> pumpScreen(
    WidgetTester tester, {
    List<Override> overrides = const [],
  }) {
    return tester.pumpWidget(
      ProviderScope(
        overrides: overrides,
        child: const MaterialApp(home: SearchScreen()),
      ),
    );
  }

  testWidgets('shows a prompt when there is no query', (tester) async {
    await pumpScreen(tester);
    await tester.pump();

    expect(find.text('Escribe para buscar productos.'), findsOneWidget);
  });

  testWidgets('shows a loading indicator while searching', (tester) async {
    final neverCompletes = Completer<List<Product>>();
    addTearDown(() => neverCompletes.complete(const []));

    await pumpScreen(
      tester,
      overrides: [
        searchQueryProvider.overrideWith((ref) => 'leche'),
        productSearchProvider.overrideWith((ref) => neverCompletes.future),
      ],
    );
    await tester.pump();

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('shows results when the search returns products', (tester) async {
    const products = [
      Product(id: 'p1', name: 'Leche entera', brand: 'Hacendado'),
      Product(id: 'p2', name: 'Leche desnatada', brand: 'Pascual'),
    ];

    await pumpScreen(
      tester,
      overrides: [
        searchQueryProvider.overrideWith((ref) => 'leche'),
        productSearchProvider.overrideWith((ref) async => products),
      ],
    );
    await tester.pumpAndSettle();

    expect(find.text('Leche entera'), findsOneWidget);
    expect(find.text('Leche desnatada'), findsOneWidget);
  });

  testWidgets('shows a message when the search returns no products', (tester) async {
    await pumpScreen(
      tester,
      overrides: [
        searchQueryProvider.overrideWith((ref) => 'leche'),
        productSearchProvider.overrideWith((ref) async => const <Product>[]),
      ],
    );
    await tester.pumpAndSettle();

    expect(find.text('Sin resultados.'), findsOneWidget);
  });

  testWidgets('shows a friendly message when the search fails', (tester) async {
    await pumpScreen(
      tester,
      overrides: [
        searchQueryProvider.overrideWith((ref) => 'leche'),
        productSearchProvider.overrideWith((ref) async => throw Exception('boom')),
      ],
    );
    await tester.pumpAndSettle();

    expect(find.text('Ha ocurrido un error inesperado.'), findsOneWidget);
  });
}
