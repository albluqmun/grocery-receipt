import 'package:flutter/material.dart';

import '../models/product.dart';

class ProductTile extends StatelessWidget {
  final Product product;
  final VoidCallback onTap;

  const ProductTile({super.key, required this.product, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final showOffName =
        product.offName != null && product.offName!.trim() != product.name.trim();
    return ListTile(
      leading: product.offImageUrl != null
          ? Image.network(
              product.offImageUrl!,
              width: 40, height: 40, fit: BoxFit.cover,
              errorBuilder: (_, __, ___) => const Icon(Icons.image_not_supported),
            )
          : const Icon(Icons.shopping_bag_outlined),
      title: Text(product.name),
      subtitle: Text([
        if (product.brand != null) product.brand!,
        if (showOffName) product.offName!,
      ].join(' · ')),
      onTap: onTap,
    );
  }
}
