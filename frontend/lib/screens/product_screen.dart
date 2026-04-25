import 'package:flutter/material.dart';

class ProductScreen extends StatelessWidget {
  final String productId;
  const ProductScreen({super.key, required this.productId});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Producto')),
      body: Center(child: Text('Product $productId — TODO')),
    );
  }
}
