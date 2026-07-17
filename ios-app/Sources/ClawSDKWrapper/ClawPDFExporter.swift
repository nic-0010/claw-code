import PDFKit
import UIKit

/// Converts a plain-text or Markdown string to a paginated PDF.
///
/// Usage:
/// ```swift
/// let pdf = ClawPDFExporter.export(text: response, title: "Business Plan")
/// let url = FileManager.default.temporaryDirectory.appendingPathComponent("output.pdf")
/// try pdf.write(to: url)
/// // Share via UIActivityViewController
/// ```
public struct ClawPDFExporter {

    /// A4 page in PDF points (72 pt/inch).
    private static let pageSize = CGSize(width: 595.2, height: 841.8)
    private static let margin: CGFloat = 56

    public static func export(text: String, title: String? = nil) -> Data {
        let contentSize = CGSize(
            width: pageSize.width - margin * 2,
            height: pageSize.height - margin * 2 - 20  // room for page footer
        )

        let storage = buildTextStorage(text: text, title: title)
        let layoutManager = NSLayoutManager()
        storage.addLayoutManager(layoutManager)

        // Add NSTextContainers until all glyphs are laid out.
        var containers: [NSTextContainer] = []
        var glyphsPlaced = 0
        repeat {
            let container = NSTextContainer(size: contentSize)
            container.lineFragmentPadding = 0
            layoutManager.addTextContainer(container)
            layoutManager.ensureLayout(for: container)
            let range = layoutManager.glyphRange(for: container)
            glyphsPlaced += range.length
            containers.append(container)
        } while glyphsPlaced < layoutManager.numberOfGlyphs

        let pageRect = CGRect(origin: .zero, size: pageSize)
        let renderer = UIGraphicsPDFRenderer(bounds: pageRect)

        return renderer.pdfData { ctx in
            let origin = CGPoint(x: margin, y: margin)
            for (idx, container) in containers.enumerated() {
                ctx.beginPage()
                let glyphRange = layoutManager.glyphRange(for: container)
                layoutManager.drawBackground(forGlyphRange: glyphRange, at: origin)
                layoutManager.drawGlyphs(forGlyphRange: glyphRange, at: origin)
                drawFooter(ctx: ctx.cgContext, page: idx + 1, total: containers.count)
            }
        }
    }

    // MARK: - Private

    private static func buildTextStorage(text: String, title: String?) -> NSTextStorage {
        let paragraphStyle = NSMutableParagraphStyle()
        paragraphStyle.lineSpacing = 3
        paragraphStyle.paragraphSpacing = 6

        let bodyAttrs: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 11),
            .foregroundColor: UIColor.black,
            .paragraphStyle: paragraphStyle,
        ]

        let result = NSMutableAttributedString()

        if let title {
            let titleStyle = NSMutableParagraphStyle()
            titleStyle.paragraphSpacing = 12
            let titleAttrs: [NSAttributedString.Key: Any] = [
                .font: UIFont.boldSystemFont(ofSize: 18),
                .foregroundColor: UIColor.black,
                .paragraphStyle: titleStyle,
            ]
            result.append(NSAttributedString(string: title + "\n\n", attributes: titleAttrs))
        }

        result.append(NSAttributedString(string: text, attributes: bodyAttrs))
        return NSTextStorage(attributedString: result)
    }

    private static func drawFooter(ctx: CGContext, page: Int, total: Int) {
        let label = "\(page) / \(total)"
        let attrs: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 9),
            .foregroundColor: UIColor.secondaryLabel,
        ]
        let str = NSAttributedString(string: label, attributes: attrs)
        let size = str.size()
        let point = CGPoint(
            x: (pageSize.width - size.width) / 2,
            y: pageSize.height - margin + 8
        )
        str.draw(at: point)
    }
}

// MARK: - UIViewController convenience

public extension UIViewController {
    /// Present a share sheet for a PDF generated from the given text.
    func sharePDF(text: String, title: String? = nil, sourceView: UIView? = nil) {
        let data = ClawPDFExporter.export(text: text, title: title)
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(title ?? "document").pdf")
        try? data.write(to: url)

        let vc = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        if let popover = vc.popoverPresentationController {
            popover.sourceView = sourceView ?? view
        }
        present(vc, animated: true)
    }
}
